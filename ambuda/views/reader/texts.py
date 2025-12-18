"""Views related to texts: title pages, sections, verses, etc."""

import json
import os
import tempfile

from flask import (
    Blueprint,
    Response,
    abort,
    jsonify,
    render_template,
    url_for,
    send_file,
    after_this_request,
)
from vidyut.lipi import transliterate, Scheme

import ambuda.database as db
import ambuda.queries as q
from ambuda.consts import TEXT_CATEGORIES
from ambuda.models.texts import TextConfig
from ambuda.utils import text_utils
from ambuda.utils import text_exports
from ambuda.utils import xml
from ambuda.utils.json_serde import AmbudaJSONEncoder
from ambuda.utils.text_quality import validate
from ambuda.views.api import bp as api
from ambuda.views.reader.schema import Block, Section

bp = Blueprint("texts", __name__)
downloads = Blueprint("downloads", __name__, url_prefix="/downloads")
bp.register_blueprint(downloads)

# A hacky list that decides which texts have parse data.
HAS_NO_PARSE = {
    "raghuvamsham",
    "bhattikavyam",
    "shatakatrayam",
    "shishupalavadham",
    "shivopanishat",
    "catuhshloki",
}

#: A special slug for single-section texts.
#:
#: Some texts are small enough that they don't have any divisions (sargas,
#: kandas). For simplicity, we represent such texts as having one section that
#: we just call "all." All such texts are called *single-section texts.*
SINGLE_SECTION_SLUG = "all"


def _prev_cur_next(sections: list[db.TextSection], slug: str):
    """Get the previous, current, and next esctions.

    :param sections: all of the sections in this text.
    :param slug: the slug for the current section.
    """
    found = False
    i = 0
    for i, s in enumerate(sections):
        if s.slug == slug:
            found = True
            break

    if not found:
        raise ValueError(f"Unknown slug {slug}")

    prev = sections[i - 1] if i > 0 else None
    cur = sections[i]
    next = sections[i + 1] if i < len(sections) - 1 else None
    return prev, cur, next


def _make_section_url(text: db.Text, section: db.TextSection | None) -> str | None:
    if section:
        return url_for("texts.section", text_slug=text.slug, section_slug=section.slug)
    else:
        return None


def _hk_to_dev(s: str) -> str:
    return transliterate(s, Scheme.HarvardKyoto, Scheme.Devanagari)


@bp.route("/")
def index():
    """Show all texts."""

    text_entries = text_utils.create_text_entries()
    return render_template("texts/index.html", text_entries=text_entries)


@bp.route("/<slug>/")
def text(slug):
    """Show a text's title page and contents."""
    text = q.text(slug)
    if text is None:
        abort(404)
    assert text

    try:
        config = TextConfig.model_validate_json(text.config)
    except Exception:
        config = TextConfig()

    prefix_titles = config.titles.fixed

    section_groups = {}
    for section in text.sections:
        key, _, _ = section.slug.rpartition(".")
        if key not in section_groups:
            section_groups[key] = []

        name = section.slug
        if section.slug.count(".") == 1:
            x, y = section.slug.split(".")
            # NOTE: experimental -- metadata paths may move at any time.
            try:
                pattern = config.titles.patterns["x.y"]
            except Exception:
                pattern = None
            if pattern:
                name = pattern.format(x=x, y=y)
        section_groups[key].append((section.slug, name))

    return render_template(
        "texts/text.html",
        text=text,
        section_groups=section_groups,
        prefix_titles=prefix_titles,
    )


@bp.route("/<slug>/about")
def text_about(slug):
    """Show a text's metadata."""
    text = q.text(slug)
    if text is None:
        abort(404)
    assert text

    header_data = xml.parse_tei_header(text.header)
    return render_template(
        "texts/text-about.html",
        text=text,
        header=header_data,
    )


@bp.route("/<slug>/resources")
def text_resources(slug):
    """Show a text's downloadable resources."""
    text = q.text(slug)
    if text is None:
        abort(404)

    return render_template("texts/text-resources.html", text=text)


@bp.route("/<slug>/validate")
def validate_text(slug):
    text = q.text(slug)
    if text is None or not text.supports_text_export:
        abort(404)
    assert text

    report = validate(text)
    return render_template("texts/text-validate.html", text=text, report=report)


@downloads.route("/<slug>.txt")
def download_plain_text(slug):
    text = q.text(slug)
    if text is None or not text.supports_text_export:
        abort(404)
    assert text

    temp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt")
    temp_path = temp.name
    temp.close()
    text_exports.create_text_file(text, temp_path)

    @after_this_request
    def remove_file(response):
        try:
            os.remove(temp_path)
        except Exception as e:
            pass
        return response

    return send_file(temp_path, as_attachment=True, download_name=f"{slug}.txt")


@downloads.route("/<slug>.xml")
def download_xml(slug):
    text = q.text(slug)
    if text is None or not text.supports_text_export:
        abort(404)
    assert text

    temp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml")
    temp_path = temp.name
    temp.close()
    text_exports.create_xml_file(text, temp_path)

    @after_this_request
    def remove_file(response):
        try:
            os.remove(temp_path)
        except Exception as e:
            pass
        return response

    return send_file(temp_path, as_attachment=True, download_name=f"{slug}.xml")


@downloads.route("/<slug>-devanagari.pdf")
def download_pdf(slug):
    text = q.text(slug)
    if text is None or not text.supports_text_export:
        abort(404)
    assert text

    temp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    temp_path = temp.name
    temp.close()
    text_exports.create_pdf(text, temp_path)

    @after_this_request
    def remove_file(response):
        try:
            os.remove(temp_path)
        except Exception as e:
            pass
        return response

    return send_file(
        temp_path,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"{slug}.pdf",
    )


@downloads.route("/<slug>-tokens.csv")
def download_tokens(slug):
    text = q.text(slug)
    if text is None or not text.has_parse_data:
        abort(404)
    assert text

    temp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    temp_path = temp.name
    temp.close()
    text_exports.create_tokens(text, temp_path)

    @after_this_request
    def remove_file(response):
        try:
            os.remove(temp_path)
        except Exception as e:
            pass
        return response

    return send_file(
        temp_path,
        mimetype="text/csv",
        as_attachment=False,
        download_name=f"{slug}-tokens.csv",
    )


@bp.route("/<text_slug>/<section_slug>")
def section(text_slug, section_slug):
    """Show a specific section of a text."""
    text_ = q.text(text_slug)
    if text_ is None:
        abort(404)
    assert text_

    try:
        prev, cur, next_ = _prev_cur_next(text_.sections, section_slug)
    except ValueError:
        abort(404)

    is_single_section_text = not prev and not next_
    if is_single_section_text:
        # Single-section texts have exactly one section whose slug should be
        # `SINGLE_SECTION_SLUG`. If the slug is anything else, abort.
        if section_slug != SINGLE_SECTION_SLUG:
            abort(404)

    has_no_parse = text_.slug in HAS_NO_PARSE

    # Fetch with content blocks
    cur = q.text_section(text_.id, section_slug)

    # TODO: this sucks
    with q.get_session() as _:
        _ = cur.blocks
        for block in cur.blocks:
            _ = block.page
            if block.page:
                _ = block.page.project
            # Eagerly load parent relationships if this is a child text
            if text_.parent_id:
                _ = block.parents
                for parent_block in block.parents:
                    _ = parent_block.page
                    if parent_block.page:
                        _ = parent_block.page.project

    blocks = []
    for block in cur.blocks:
        page = block.page
        page_url = None
        if page:
            page_url = url_for(
                "proofing.page.edit",
                project_slug=page.project.slug,
                page_slug=page.slug,
            )

        # Fetch parent blocks if this text has a parent
        parent_blocks = None
        if text_.parent_id and block.parents:
            parent_blocks = []
            for parent_block in block.parents:
                parent_page = parent_block.page
                parent_page_url = None
                if parent_page:
                    parent_page_url = url_for(
                        "proofing.page.edit",
                        project_slug=parent_page.project.slug,
                        page_slug=parent_page.slug,
                    )
                parent_blocks.append(
                    Block(
                        slug=parent_block.slug,
                        mula=xml.transform_text_block(parent_block.xml),
                        page_url=parent_page_url,
                    )
                )

        blocks.append(
            Block(
                slug=block.slug,
                mula=xml.transform_text_block(block.xml),
                page_url=page_url,
                parent_blocks=parent_blocks,
            )
        )

    data = Section(
        text_title=_hk_to_dev(text_.title),
        section_title=_hk_to_dev(cur.title),
        blocks=blocks,
        prev_url=_make_section_url(text_, prev),
        next_url=_make_section_url(text_, next_),
    )
    json_payload = json.dumps(data, cls=AmbudaJSONEncoder)

    return render_template(
        "texts/section.html",
        text=text_,
        prev=prev,
        section=cur,
        next=next_,
        json_payload=json_payload,
        html_blocks=data.blocks,
        has_no_parse=has_no_parse,
        is_single_section_text=is_single_section_text,
    )


@api.route("/texts/<text_slug>/blocks/<block_slug>")
def block_htmx(text_slug, block_slug):
    text = q.text(text_slug)
    if text is None:
        abort(404)

    block = q.block(text.id, block_slug)
    if not block:
        abort(404)

    html_block = xml.transform_text_block(block.xml)
    return render_template(
        "htmx/text-block.html",
        slug=block.slug,
        html=html_block,
    )


@api.route("/texts/<text_slug>/<section_slug>")
def reader_json(text_slug, section_slug):
    # NOTE: currently unused, since we bootstrap from a JSON blob in the
    # original request.
    text_ = q.text(text_slug)
    if text_ is None:
        abort(404)
    assert text_

    try:
        prev, cur, next_ = _prev_cur_next(text_.sections, section_slug)
    except ValueError:
        abort(404)

    with q.get_session() as _:
        html_blocks = [xml.transform_text_block(b.xml) for b in cur.blocks]

    data = Section(
        text_title=_hk_to_dev(text_.title),
        section_title=_hk_to_dev(cur.title),
        blocks=html_blocks,
        prev_url=_make_section_url(text, prev),
        next_url=_make_section_url(text, next_),
    )
    return jsonify(data)
