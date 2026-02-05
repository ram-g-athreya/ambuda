"""Publishing routes for converting proofing projects into published texts."""

import dataclasses as dc
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from lxml import etree
from xml.etree import ElementTree as ET

from slugify import slugify
from flask import (
    Blueprint,
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

    diffs = []
    max_len = max(len(new_blocks), len(existing_blocks))
    for i in range(max_len):
        old_xml = existing_blocks[i].xml if i < len(existing_blocks) else None
        new_xml = new_blocks[i] if i < len(new_blocks) else None

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
        # TODO: align existing and new sections to minimize diff thrash, keep alignment.
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

    existing_blocks = {
        b.slug
        for b in session.execute(
            sqla.select(db.TextBlock).where(db.TextBlock.text_id == text.id)
        )
        .scalars()
        .all()
    }
    doc_blocks = {b.slug for s in document_data.sections for b in s.blocks}

    if existing_blocks != doc_blocks:
        old_blocks = existing_blocks - doc_blocks
        new_blocks = doc_blocks - existing_blocks

        if old_blocks:
            session.execute(
                sqla.delete(db.TextBlock).where(
                    db.TextBlock.text_id == text.id,
                    db.TextBlock.slug.in_(old_blocks),
                )
            )

        existing_blocks = existing_blocks - old_blocks
    else:
        new_blocks = set()

    existing_blocks_map = {}
    if existing_blocks:
        existing_blocks_list = (
            session.execute(
                sqla.select(db.TextBlock).where(
                    db.TextBlock.text_id == text.id,
                    db.TextBlock.slug.in_(existing_blocks),
                )
            )
            .scalars()
            .all()
        )
        existing_blocks_map = {b.slug: b for b in existing_blocks_list}

    block_index = 0
    for doc_section in document_data.sections:
        section = section_map[doc_section.slug]

        for block in doc_section.blocks:
            block_index += 1

            if block.slug in existing_blocks_map:
                existing_block = existing_blocks_map[block.slug]
                existing_block.xml = block.xml
                existing_block.n = block_index
                existing_block.section_id = section.id
                existing_block.page_id = block.page_id
            elif block.slug in new_blocks:
                new_block = db.TextBlock(
                    text_id=text.id,
                    section_id=section.id,
                    slug=block.slug,
                    xml=block.xml,
                    n=block_index,
                    page_id=block.page_id,
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

    session.commit()

    if created_count > 0:
        flash(f"Created {created_count} text(s)", "success")
    if updated_count > 0:
        flash(f"Updated {updated_count} text(s)", "success")

    return redirect(url_for("proofing.publish.config", slug=project_slug))
