"""Tutorial system for learning the proofing editor."""

import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from flask import Blueprint, abort, jsonify, render_template, request, session

bp = Blueprint("tutorial", __name__, url_prefix="/tutorial")


@dataclass(frozen=True)
class Lesson:
    """Metadata for a tutorial lesson. Content lives in templates."""

    id: int
    title: str
    summary: str
    image_url: str | None = None


LESSONS = [
    Lesson(
        id=1,
        title="Basic transcription",
        summary="Fix common OCR errors in a simple paragraph.",
    ),
    Lesson(
        id=2,
        title="Structuring blocks",
        summary="Split text into proper heading and verse blocks.",
    ),
]

LESSONS_BY_ID = {lesson.id: lesson for lesson in LESSONS}

# Expected answers for each lesson (XML, same format as ProofingEditor.getText()).
# Compared structurally — whitespace and attribute order don't matter.
EXPECTED_CONTENT = {
    1: (
        "<page>\n"
        "<p>The sage Valmiki composed the great epic Ramayana. "
        "It tells the story of Rama, prince of Ayodhya, "
        "and his quest to rescue his wife Sita from the demon king Ravana.</p>\n"
        "</page>"
    ),
    2: (
        "<page>\n"
        "<heading>Chapter One</heading>\n"
        "<verse>dharma-kShetre kuru-kShetre\n"
        "samavetA yuyutsavaH |\n"
        "mAmakAH pANDavAsh caiva\n"
        "kim akurvata saMjaya ||</verse>\n"
        "</page>"
    ),
}

# ---------- XML structural comparison ----------

_BLOCK_ATTRS = ("text", "n", "mark", "lang", "merge-next")


def _normalize_text(text: str) -> str:
    """Collapse whitespace within a text string for comparison."""
    return re.sub(r"\s+", " ", text.strip())


def _xml_trees_equal(user_xml: str, expected_xml: str) -> bool:
    """Compare two XML strings structurally.

    Two documents are equal if they have:
    - The same number of block children
    - Each block has the same tag (type) and relevant attributes
    - Each block has the same text content (after normalizing whitespace)
    - Inline mark structure matches (same marks wrapping same text)
    """
    try:
        user_root = ET.fromstring(user_xml)
        expected_root = ET.fromstring(expected_xml)
    except ET.ParseError:
        return False

    user_blocks = list(user_root)
    expected_blocks = list(expected_root)

    if len(user_blocks) != len(expected_blocks):
        return False

    for user_block, expected_block in zip(user_blocks, expected_blocks):
        if not _blocks_equal(user_block, expected_block):
            return False

    return True


def _blocks_equal(a: ET.Element, b: ET.Element) -> bool:
    """Compare two block elements structurally."""
    if a.tag != b.tag:
        return False

    for attr in _BLOCK_ATTRS:
        if a.get(attr) != b.get(attr):
            return False

    return _inline_content_equal(a, b)


def _inline_content_equal(a: ET.Element, b: ET.Element) -> bool:
    """Compare inline content of two elements, including marks."""
    a_parts = _flatten_inline(a)
    b_parts = _flatten_inline(b)

    if len(a_parts) != len(b_parts):
        return False

    for (a_marks, a_text), (b_marks, b_text) in zip(a_parts, b_parts):
        if a_marks != b_marks:
            return False
        if _normalize_text(a_text) != _normalize_text(b_text):
            return False

    return True


def _flatten_inline(elem: ET.Element) -> list[tuple[tuple[str, ...], str]]:
    """Flatten inline content into (marks, text) pairs, dropping empty text."""
    parts: list[tuple[tuple[str, ...], str]] = []
    _collect_inline(elem, (), parts)
    return [(marks, text) for marks, text in parts if text.strip()]


def _collect_inline(
    elem: ET.Element,
    marks: tuple[str, ...],
    out: list[tuple[tuple[str, ...], str]],
) -> None:
    """Recursively collect (marks, text) pairs from an element."""
    if elem.text:
        out.append((marks, elem.text))

    for child in elem:
        child_marks = marks + (child.tag,)
        _collect_inline(child, child_marks, out)
        if child.tail:
            out.append((marks, child.tail))


# ---------- Routes ----------


@bp.route("/")
def index():
    completed = session.get("tutorial_completed", [])
    return render_template(
        "proofing/tutorial/index.html",
        lessons=LESSONS,
        completed=completed,
    )


@bp.route("/<int:lesson_id>")
def lesson(lesson_id):
    lesson_data = LESSONS_BY_ID.get(lesson_id)
    if lesson_data is None:
        abort(404)

    lesson_ids = [l.id for l in LESSONS]
    idx = lesson_ids.index(lesson_id)
    prev_id = lesson_ids[idx - 1] if idx > 0 else None
    next_id = lesson_ids[idx + 1] if idx < len(lesson_ids) - 1 else None

    completed = session.get("tutorial_completed", [])
    return render_template(
        f"proofing/tutorial/lessons/{lesson_id}.html",
        lesson=lesson_data,
        prev_id=prev_id,
        next_id=next_id,
        is_completed=lesson_id in completed,
    )


@bp.route("/<int:lesson_id>/check", methods=["POST"])
def check(lesson_id):
    expected = EXPECTED_CONTENT.get(lesson_id)
    if expected is None:
        return jsonify({"correct": False, "message": "Lesson not found."}), 404

    data = request.get_json(silent=True)
    if not data or "content" not in data:
        return jsonify({"correct": False, "message": "No content provided."}), 400

    if _xml_trees_equal(data["content"], expected):
        completed = session.get("tutorial_completed", [])
        if lesson_id not in completed:
            completed.append(lesson_id)
            session["tutorial_completed"] = completed
        return jsonify({"correct": True, "message": "Correct! Well done."})

    return jsonify(
        {
            "correct": False,
            "message": "Not quite right. Check your work and try again.",
        }
    )
