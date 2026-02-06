"""Publishing routes for converting proofing projects into published texts."""

import dataclasses as dc
import difflib
import hashlib
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from lxml import etree
from xml.etree import ElementTree as ET

from slugify import slugify
from flask import (
    Blueprint,
    current_app,
    flash,
    render_template,
    request,
    url_for,
)
from flask_babel import lazy_gettext as _l
import sqlalchemy as sqla
from werkzeug.exceptions import abort
from werkzeug.utils import redirect

import ambuda.utils.text_publishing as publishing_utils
from ambuda import database as db
from ambuda import queries as q
from ambuda.enums import SitePageStatus
from ambuda.models.proofing import (
    LanguageCode,
    ProjectStatus,
    PublishConfig,
    ProjectConfig,
)
from ambuda.models.texts import TextStatus
from ambuda.utils import diff as diff_utils
from ambuda.utils import project_utils
from ambuda.utils.s3 import S3Path
from ambuda.views.proofing.decorators import p2_required


_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def _validate_slug(slug: str) -> str | None:
    if not slug:
        return "Slug is required."
    if not _SLUG_RE.match(slug):
        return (
            f"Invalid slug '{slug}': must contain only lowercase letters, digits, "
            "and hyphens; must start and end with a letter or digit."
        )
    if "--" in slug:
        return f"Invalid slug '{slug}': consecutive dashes are not allowed."
    return None


def _align_sequences(
    old_items: list, new_items: list, *, key=None
) -> list[tuple[int | None, int | None]]:
    """Align two sequences to minimize the total diff.

    Uses SequenceMatcher (LCS-based) to find an optimal alignment between
    the old and new sequences.  Within ``replace`` regions the items are
    paired positionally; excess items become pure inserts or deletes.

    Args:
        old_items: The old sequence.
        new_items: The new sequence.
        key: Optional callable to extract a comparison key from each item.
             When *None*, items are compared directly.

    Returns:
        List of ``(old_index | None, new_index | None)`` pairs.  Both
        indices are set for matched or changed items; only one is set for
        pure insertions or deletions.
    """
    if key:
        old_keys = [key(item) for item in old_items]
        new_keys = [key(item) for item in new_items]
    else:
        old_keys = list(old_items)
        new_keys = list(new_items)

    matcher = difflib.SequenceMatcher(a=old_keys, b=new_keys, autojunk=False)
    pairs: list[tuple[int | None, int | None]] = []
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op == "equal":
            for i, j in zip(range(a0, a1), range(b0, b1)):
                pairs.append((i, j))
        elif op == "replace":
            a_len = a1 - a0
            b_len = b1 - b0
            common = min(a_len, b_len)
            for k in range(common):
                pairs.append((a0 + k, b0 + k))
            for k in range(common, a_len):
                pairs.append((a0 + k, None))
            for k in range(common, b_len):
                pairs.append((None, b0 + k))
        elif op == "delete":
            for i in range(a0, a1):
                pairs.append((i, None))
        elif op == "insert":
            for j in range(b0, b1):
                pairs.append((None, j))
    return pairs


bp = Blueprint("publish", __name__)


@bp.route("/<slug>/publish", methods=["GET", "POST"])
@p2_required
def config(slug):
    """Configure publish settings for the project."""
    project_ = q.project(slug)
    if project_ is None:
        abort(404)

    assert project_
    if request.method == "POST":
        publish_json = request.form.get("config", "")
        default = lambda: render_template(
            "proofing/projects/publish.html",
            project=project_,
            config=publish_json,
        )

        try:
            new_config = ProjectConfig.model_validate_json(publish_json)
        except Exception as e:
            flash(f"Validation error: {e}", "error")
            return default()

        for pc in new_config.publish:
            slug_error = _validate_slug(pc.slug)
            if slug_error:
                flash(slug_error, "error")
                return default()

        session = q.get_session()
        try:
            old_config = ProjectConfig.model_validate_json(project_.config or "{}")
        except Exception:
            old_config = ProjectConfig()
        old_slugs = {c.slug for c in old_config.publish}

        for pc in new_config.publish:
            if pc.slug not in old_slugs:
                existing_text = session.execute(
                    sqla.select(db.Text).where(db.Text.slug == pc.slug)
                ).scalar_one_or_none()
                if existing_text:
                    flash(
                        f"A text with slug '{pc.slug}' already exists. "
                        "Please choose a different slug.",
                        "error",
                    )
                    return default()

        # TODO: tighten restrictions here -- should only be able to update 'publish' ?
        if new_config != old_config:
            project_.config = new_config.model_dump_json()
            session.commit()
            flash("Configuration saved successfully.", "success")
        else:
            flash("No changes to save.", "info")

        return redirect(url_for("proofing.publish.config", slug=slug))

    try:
        project_config = ProjectConfig.model_validate_json(project_.config or "{}")
    except Exception:
        flash("Project config is invalid. Please contact an admin user.", "error")
        return redirect(url_for("proofing.index"))

    config = project_config.model_dump()
    config_schema = PublishConfig.model_json_schema()

    # Get all genres and authors for datalist
    session = q.get_session()
    genres = (
        session.execute(sqla.select(db.Genre).order_by(db.Genre.name)).scalars().all()
    )
    authors = (
        session.execute(sqla.select(db.Author).order_by(db.Author.name)).scalars().all()
    )

    language_labels = {code.value: code.label for code in LanguageCode}

    return render_template(
        "proofing/projects/publish.html",
        project=project_,
        publish_config=config,
        publish_config_schema=config_schema,
        language_labels=language_labels,
        genres=genres,
        authors=authors,
    )


@bp.route("/<project_slug>/publish/<text_slug>/preview", methods=["GET"])
@p2_required
def preview(project_slug, text_slug):
    """Preview the changes that will be made when publishing a single text."""
    project_ = q.project(project_slug)
    if project_ is None:
        abort(404)

    assert project_
    config_page = lambda: redirect(
        url_for("proofing.publish.config", slug=project_slug)
    )
    if not project_.config:
        flash("No publish configuration found. Please configure first.", "error")
        return config_page()
    try:
        project_config = ProjectConfig.model_validate_json(project_.config or "{}")
    except Exception as e:
        flash("Could not validate project config", "error")
        return config_page()
    if not project_config.publish:
        flash("No publish configuration found. Please configure first.", "error")
        return config_page()

    config = next((c for c in project_config.publish if c.slug == text_slug), None)
    if not config:
        flash(f"No publish configuration found for text '{text_slug}'.", "error")
        return config_page()

    session = q.get_session()

    existing_text = session.execute(
        sqla.select(db.Text).where(db.Text.slug == text_slug)
    ).scalar_one_or_none()

    existing_blocks = []
    if existing_text:
        existing_blocks = (
            session.execute(
                sqla.select(db.TextBlock)
                .where(db.TextBlock.text_id == existing_text.id)
                .order_by(db.TextBlock.n)
            )
            .scalars()
            .all()
        )

    with tempfile.NamedTemporaryFile(delete_on_close=False) as fp:
        fp.close()
        _ = publishing_utils.create_tei_document(project_, config, Path(fp.name))
        document = publishing_utils.parse_tei_document(Path(fp.name))
    new_blocks = [b.xml for section in document.sections for b in section.blocks]

    old_xmls = [b.xml for b in existing_blocks]
    alignment = _align_sequences(old_xmls, new_blocks)

    diffs = []
    for old_idx, new_idx in alignment:
        old_xml = old_xmls[old_idx] if old_idx is not None else None
        new_xml = new_blocks[new_idx] if new_idx is not None else None

        if old_xml is None and new_xml is not None:
            x = ET.fromstring(new_xml)
            ET.indent(x, "  ")
            new_xml = ET.tostring(x, encoding="unicode")
            diffs.append(
                {
                    "type": "added",
                    "diff": new_xml,
                }
            )
        elif old_xml is not None and new_xml is None:
            diffs.append(
                {
                    "type": "removed",
                    "diff": old_xml,
                }
            )
        elif old_xml != new_xml:
            diffs.append(
                {
                    "type": "changed",
                    "diff": diff_utils.revision_diff(old_xml, new_xml),
                }
            )

    parent_info = None
    if config.parent_slug:
        parent_text = session.execute(
            sqla.select(db.Text).where(db.Text.slug == config.parent_slug)
        ).scalar_one_or_none()
        if parent_text:
            parent_info = {"slug": parent_text.slug, "title": parent_text.title}

    preview = {
        "slug": config.slug,
        "title": config.title,
        "target": config.target,
        "is_new": existing_text is None,
        "parent": parent_info,
        "diffs": diffs,
    }

    return render_template(
        "proofing/projects/publish-preview.html",
        project=project_,
        text_slug=text_slug,
        previews=[preview],  # Keep as list for template compatibility
    )


@bp.route("/<project_slug>/publish/<text_slug>/create", methods=["POST"])
@p2_required
def create(project_slug, text_slug):
    """Create or update texts based on the specified publish config."""
    config_page = lambda: redirect(
        url_for("proofing.publish.config", slug=project_slug)
    )

    project_ = q.project(project_slug)
    if project_ is None:
        abort(404)
    assert project_
    if not project_.config:
        flash("No publish configuration found. Please configure first.", "error")
        return config_page()
    try:
        project_config = ProjectConfig.model_validate_json(project_.config)
    except Exception:
        flash("Could not validate project config.", "error")
        return config_page()
    config = next((c for c in project_config.publish if c.slug == text_slug), None)
    if not config:
        flash(f"No publish configuration found for text '{text_slug}'.", "error")
        return config_page()

    session = q.get_session()
    created_count = 0
    updated_count = 0
    texts_map = {}

    with tempfile.NamedTemporaryFile(delete_on_close=False) as fp:
        fp.close()
        document_data = publishing_utils.create_tei_document(
            project_, config, Path(fp.name)
        )
        header = ""
        _ns = "{http://www.tei-c.org/ns/1.0}"
        for event, elem in etree.iterparse(fp.name, events=("end",)):
            if elem.tag == f"{_ns}teiHeader":
                for x in elem.getiterator():
                    x.tag = etree.QName(x).localname
                etree.cleanup_namespaces(elem)
                header = ET.tostring(elem, encoding="unicode")
                break

        # Upload TEI XML to S3
        tei_path = Path(fp.name)
        tei_size = tei_path.stat().st_size
        sha256_hash = hashlib.sha256()
        with open(tei_path, "rb") as hash_f:
            for chunk in iter(lambda: hash_f.read(4096), b""):
                sha256_hash.update(chunk)
        tei_checksum = sha256_hash.hexdigest()

        export_slug = f"{config.slug}.xml"
        bucket = current_app.config["S3_BUCKET"]
        tei_s3 = S3Path(bucket, f"text-exports/{export_slug}")
        tei_s3.upload_file(tei_path)

    text = q.text(config.slug)
    is_new_text = False
    if not text:
        text = db.Text(
            slug=config.slug,
            title=config.title,
            published_at=datetime.now(UTC),
            project_id=project_.id,
        )
        session.add(text)
        session.flush()
        is_new_text = True

    text.header = header
    text.project_id = project_.id
    text.language = config.language
    text.title = config.title

    if config.author:
        author = session.execute(
            sqla.select(db.Author).where(db.Author.name == config.author)
        ).scalar_one_or_none()
        if not author:
            author = db.Author(name=config.author, slug=slugify(config.author))
            session.add(author)
            session.flush()
        text.author_id = author.id
    else:
        text.author_id = None

    if config.genre:
        genre = session.execute(
            sqla.select(db.Genre).where(db.Genre.name == config.genre)
        ).scalar_one_or_none()
        if not genre:
            genre = db.Genre(name=config.genre)
            session.add(genre)
            session.flush()
        text.genre_id = genre.id
    else:
        text.genre_id = None

    if SitePageStatus.R0.value in document_data.page_statuses:
        text.status = TextStatus.P0
    elif SitePageStatus.R1.value in document_data.page_statuses:
        text.status = TextStatus.P1
    else:
        text.status = TextStatus.P2

    existing_sections = {s.slug for s in text.sections}
    doc_sections = {s.slug for s in document_data.sections}
    section_map = {s.slug: s for s in text.sections}

    if existing_sections != doc_sections:
        new_sections = doc_sections - existing_sections
        old_sections = existing_sections - doc_sections

        for old_slug in old_sections:
            old_section = next((s for s in text.sections if s.slug == old_slug), None)
            if old_section:
                session.delete(old_section)
                del section_map[old_slug]

        for new_slug in new_sections:
            doc_section = next(
                (s for s in document_data.sections if s.slug == new_slug), None
            )
            if doc_section:
                new_section = db.TextSection(
                    text_id=text.id,
                    slug=new_slug,
                    title=new_slug,
                )
                session.add(new_section)
                section_map[new_slug] = new_section

        session.flush()

    existing_blocks_list = (
        session.execute(
            sqla.select(db.TextBlock)
            .where(db.TextBlock.text_id == text.id)
            .order_by(db.TextBlock.n)
        )
        .scalars()
        .all()
    )

    new_doc_blocks = []
    block_sections = []
    for doc_section in document_data.sections:
        section = section_map[doc_section.slug]
        for block in doc_section.blocks:
            new_doc_blocks.append(block)
            block_sections.append(section)

    old_xmls = [b.xml for b in existing_blocks_list]
    new_xmls = [b.xml for b in new_doc_blocks]
    alignment = _align_sequences(old_xmls, new_xmls)

    block_index = 0
    for old_idx, new_idx in alignment:
        if old_idx is not None and new_idx is not None:
            block_index += 1
            existing_block = existing_blocks_list[old_idx]
            doc_block = new_doc_blocks[new_idx]
            existing_block.slug = doc_block.slug
            existing_block.xml = doc_block.xml
            existing_block.n = block_index
            existing_block.section_id = block_sections[new_idx].id
            existing_block.page_id = doc_block.page_id
        elif old_idx is not None:
            session.delete(existing_blocks_list[old_idx])
        else:
            block_index += 1
            doc_block = new_doc_blocks[new_idx]
            new_block = db.TextBlock(
                text_id=text.id,
                section_id=block_sections[new_idx].id,
                slug=doc_block.slug,
                xml=doc_block.xml,
                n=block_index,
                page_id=doc_block.page_id,
            )
            session.add(new_block)

    texts_map[config.slug] = text
    if is_new_text:
        created_count += 1
    else:
        updated_count += 1

    session.flush()

    if config.parent_slug:
        text = texts_map[config.slug]
        parent_text = texts_map.get(config.parent_slug) or q.text(config.parent_slug)
        if parent_text:
            text.parent_id = parent_text.id

    session.flush()

    if config.parent_slug:
        text = texts_map[config.slug]
        parent_text = texts_map.get(config.parent_slug) or q.text(config.parent_slug)
        if parent_text:
            parent_blocks = (
                session.execute(
                    sqla.select(db.TextBlock)
                    .where(db.TextBlock.text_id == parent_text.id)
                    .order_by(db.TextBlock.n)
                )
                .scalars()
                .all()
            )

            child_blocks = (
                session.execute(
                    sqla.select(db.TextBlock)
                    .where(db.TextBlock.text_id == text.id)
                    .order_by(db.TextBlock.n)
                )
                .scalars()
                .all()
            )

            child_block_ids = [b.id for b in child_blocks]
            if child_block_ids:
                session.execute(
                    sqla.delete(db.text_block_associations).where(
                        db.text_block_associations.c.child_id.in_(child_block_ids)
                    )
                )

            parent_blocks_by_slug = {b.slug: b for b in parent_blocks}
            for child_block in child_blocks:
                parent_block = parent_blocks_by_slug.get(child_block.slug)
                if parent_block:
                    session.execute(
                        sqla.insert(db.text_block_associations).values(
                            parent_id=parent_block.id,
                            child_id=child_block.id,
                        )
                    )

    # Create or update the XML export record
    text_export = q.text_export(export_slug)
    if text_export:
        text_export.s3_path = tei_s3.path
        text_export.size = tei_size
        text_export.sha256_checksum = tei_checksum
        text_export.updated_at = datetime.now(UTC)
    else:
        text_export = db.TextExport(
            text_id=text.id,
            slug=export_slug,
            export_type="xml",
            s3_path=tei_s3.path,
            size=tei_size,
            sha256_checksum=tei_checksum,
        )
        session.add(text_export)

    session.commit()

    if created_count > 0:
        flash(f"Created {created_count} text(s)", "success")
    if updated_count > 0:
        flash(f"Updated {updated_count} text(s)", "success")

    return redirect(url_for("proofing.publish.config", slug=project_slug))
