"""All API endpoints, registered under the /api prefix.

Previously, API routes were scattered across individual view modules that
imported this blueprint. They are now co-located here for discoverability.
"""

import defusedxml.ElementTree as DET
from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from pydantic import BaseModel
from sqlalchemy import select

from ambuda import database as db
from ambuda import queries as q
from ambuda.rate_limit import limiter
from ambuda.utils import google_ocr, llm_structuring, xml
from ambuda.utils import word_parses as parse_utils
from ambuda.utils.parse_alignment import align_text_with_parse
from ambuda.utils.project_structuring import ProofPage, split_plain_text_to_blocks
from ambuda.views.proofing.decorators import p2_required

bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# Proofing
# ---------------------------------------------------------------------------


class AutoStructureRequest(BaseModel):
    """Request model for auto-structuring page content."""

    content: str
    match_stage: bool = False
    match_speaker: bool = False
    match_chaya: bool = False


@bp.route("/ocr/<project_slug>/<page_slug>/")
@limiter.limit("15/hour")
@login_required
def ocr_api(project_slug, page_slug):
    """Apply Google OCR to the given page."""
    project_ = q.project(project_slug)
    if project_ is None:
        abort(404)
    assert project_

    page_ = q.page(project_.id, page_slug)
    if not page_:
        abort(404)
    assert page_

    ocr_response = google_ocr.run(
        page_,
        current_app.config.get("S3_BUCKET"),
        current_app.config.get("CLOUDFRONT_BASE_URL"),
    )
    ocr_text = ocr_response.text_content

    structured_data = ProofPage.from_content_and_page_id(ocr_text, page_.id)
    ret = structured_data.to_xml_string()
    return ret


@bp.route("/llm-structuring/<project_slug>/<page_slug>/", methods=["POST"])
@limiter.limit("10/hour")
@p2_required
def llm_structuring_api(project_slug, page_slug):
    project_ = q.project(project_slug)
    if project_ is None:
        abort(404)
    assert project_

    page_ = q.page(project_.id, page_slug)
    if not page_:
        abort(404)
    assert page_

    content = request.json.get("content", "")
    if not content:
        return "Error: No content provided", 400

    try:
        api_key = current_app.config.get("GEMINI_API_KEY")
        if not api_key:
            current_app.logger.error("GEMINI_API_KEY not configured")
            return "Error: LLM service is not available", 500

        structured_content = llm_structuring.run(content, api_key)
        return structured_content
    except Exception as e:
        current_app.logger.error(f"LLM structuring failed: {e}")
        return "Error: LLM structuring failed", 500


@bp.route("/proofing/auto-structure", methods=["POST"])
@limiter.limit("60/hour")
@login_required
def auto_structure_api():
    """Apply auto-structuring heuristics to the page content."""
    if not request.json:
        return jsonify({"error": "No data provided"}), 400

    try:
        req = AutoStructureRequest.model_validate(request.json)
    except Exception as e:
        current_app.logger.warning(f"Invalid auto-structure request: {e}")
        return jsonify({"error": "Invalid request data"}), 400

    try:
        root = DET.fromstring(req.content)
        if root.tag != "page":
            return jsonify({"error": "Invalid XML: root tag must be 'page'"}), 400

        text = "".join(root.itertext())
        blocks = split_plain_text_to_blocks(
            text,
            match_stage=req.match_stage,
            match_speaker=req.match_speaker,
            match_chaya=req.match_chaya,
            ignore_non_devanagari=True,
        )
        page = ProofPage(id=0, blocks=blocks)
        xml_str = page.to_xml_string()
        return jsonify({"content": xml_str})

    except Exception as e:
        current_app.logger.error(f"Auto-structuring failed: {e}")
        return jsonify({"error": "Auto-structuring failed"}), 500


@bp.route("/proofing/<project_slug>/<page_slug>/history")
def page_history_api(project_slug, page_slug):
    from ambuda.views.proofing.page import _get_page_context

    ctx = _get_page_context(project_slug, page_slug)
    if ctx is None:
        abort(404)

    assert ctx
    revisions = []
    for r in reversed(ctx.cur.revisions):
        revisions.append(
            {
                "id": r.id,
                "created": r.created.strftime("%Y-%m-%d %H:%M"),
                "author": r.author.username,
                "summary": r.summary or "",
                "status": r.status.name,
                "revision_url": url_for(
                    "proofing.page.revision",
                    project_slug=project_slug,
                    page_slug=page_slug,
                    revision_id=r.id,
                    _external=True,
                ),
                "author_url": url_for(
                    "user.summary", username=r.author.username, _external=True
                ),
            }
        )

    return jsonify({"revisions": revisions})


# ---------------------------------------------------------------------------
# Texts / Reader
# ---------------------------------------------------------------------------


@bp.route("/texts/<text_slug>/blocks/<block_slug>")
def block_htmx(text_slug, block_slug):
    text = q.text(text_slug)
    if text is None:
        abort(404)
    assert text

    block = q.block(text.id, block_slug)
    if not block:
        abort(404)
    assert block

    html_block = xml.transform_text_block(block.xml)
    return render_template(
        "htmx/text-block.html",
        slug=block.slug,
        html=html_block,
    )


@bp.route("/texts/<text_slug>/<section_slug>")
def reader_json(text_slug, section_slug):
    """Return section data as JSON. Currently unused (bootstrapped inline)."""
    from ambuda.views.reader.schema import Section
    from ambuda.views.reader.texts import _hk_to_dev, _make_section_url, _prev_cur_next

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
        prev_url=_make_section_url(text_, prev),
        next_url=_make_section_url(text_, next_),
    )
    return jsonify(data)


@bp.route("/bookmarks/toggle", methods=["POST"])
def toggle_bookmark():
    """Toggle a bookmark on a text block."""

    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json()
    block_slug = data.get("block_slug")

    if not block_slug:
        return jsonify({"error": "block_slug is required"}), 400

    session = q.get_session()

    block = session.scalar(select(db.TextBlock).where(db.TextBlock.slug == block_slug))
    if not block:
        return jsonify({"error": "Block not found"}), 404

    existing_bookmark = session.scalar(
        select(db.TextBlockBookmark).where(
            db.TextBlockBookmark.user_id == current_user.id,
            db.TextBlockBookmark.block_id == block.id,
        )
    )

    if existing_bookmark:
        session.delete(existing_bookmark)
        session.commit()
        return jsonify({"bookmarked": False, "block_slug": block_slug})
    else:
        bookmark = db.TextBlockBookmark(
            user_id=current_user.id,
            block_id=block.id,
        )
        session.add(bookmark)
        session.commit()
        return jsonify({"bookmarked": True, "block_slug": block_slug})


# ---------------------------------------------------------------------------
# Dictionaries
# ---------------------------------------------------------------------------


@bp.route("/dictionaries/<list:sources>/<query>")
def entry_htmx(sources, query):
    from ambuda.views.dictionaries import _fetch_entries, _get_dictionary_data

    dictionaries = _get_dictionary_data()
    sources = [s for s in sources if s in dictionaries]
    if not sources:
        abort(404)

    entries = _fetch_entries(sources, query)
    return render_template(
        "htmx/dictionary-results.html",
        query=query,
        entries=entries,
        dictionaries=dictionaries,
    )


# ---------------------------------------------------------------------------
# Bharati (grammar / morphology)
# ---------------------------------------------------------------------------


@bp.route("/bharati/query/<query>")
def bharati_query(query):
    from vidyut.lipi import Scheme, detect, transliterate

    from ambuda.views.bharati import _get_kosha_entries

    query = query.strip()
    input_scheme = detect(query) or Scheme.HarvardKyoto
    query = transliterate(query, input_scheme, Scheme.Slp1)

    entries = _get_kosha_entries(query)
    return render_template("htmx/bharati-query.html", query=query, entries=entries)


# ---------------------------------------------------------------------------
# Parses
# ---------------------------------------------------------------------------


@bp.route("/parses/<text_slug>/<block_slug>")
def block_parse_htmx(text_slug, block_slug):
    text = q.text_meta(text_slug)
    if text is None:
        abort(404)

    block = q.block(text.id, block_slug)
    if block is None:
        abort(404)

    parse = q.block_parse(block.id)
    if not parse:
        abort(404)

    tokens = parse_utils.extract_tokens(parse.data)
    aligned = align_text_with_parse(block.xml, tokens)
    return render_template(
        "htmx/parsed-tokens.html",
        text_slug=text_slug,
        block_slug=block_slug,
        aligned=aligned,
    )
