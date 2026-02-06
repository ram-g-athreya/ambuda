"""Utilities for working with diffs."""

import difflib

import regex
from markupsafe import Markup, escape


class GraphemeList(list):
    """Represents a string split into graphemes.
    Taking a slice of the list returns a string (rather
    than a list) so that the list can be passed into
    difflib.SequenceMatcher properly."""

    def __getitem__(self, key):
        if isinstance(key, slice):
            return "".join(super().__getitem__(key))
        return super().__getitem__(key)


def _split_graphemes(s: str) -> GraphemeList:
    """Splits the given string into graphemes and returns
    a list of those graphemes."""

    # \X matches by grapheme, per http://www.unicode.org/reports/tr29/.
    return GraphemeList(regex.findall(r"\X", s))


def _create_markup(tag: str, s: str) -> tuple[Markup, Markup, Markup]:
    """Create markup for the given tag and string,
    used to denote additions / deletions for diffs."""
    assert tag in ("ins", "del")
    attr = ""
    if s in ("\n", "\r\n"):
        # Display newline changes as block so they show up in the diff.
        attr = ' class="block"'
    return (
        Markup(f"<{tag}{attr}>"),
        escape(s),
        Markup(f"</{tag}>"),
    )


def revision_diff_ops(old: str, new: str) -> list[dict]:
    """Return a structured list of diff operations between *old* and *new*.

    Each element is a dict with keys ``op`` (one of ``"equal"``,
    ``"insert"``, ``"delete"``, ``"replace"``), ``old``, and ``new``.
    """
    matcher = difflib.SequenceMatcher(a=_split_graphemes(old), b=_split_graphemes(new))
    ops: list[dict] = []
    for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
        old_text = matcher.a[a0:a1]
        new_text = matcher.b[b0:b1]
        if opcode == "equal":
            ops.append({"op": "equal", "old": old_text, "new": new_text})
        elif opcode == "insert":
            ops.append({"op": "insert", "old": "", "new": new_text})
        elif opcode == "delete":
            ops.append({"op": "delete", "old": old_text, "new": ""})
        elif opcode == "replace":
            ops.append({"op": "replace", "old": old_text, "new": new_text})
        else:
            raise RuntimeError(f"Unexpected opcode {opcode}")
    return ops


def revision_diff(old: str, new: str) -> str:
    """Generate a diff from old and new strings, wrapping
    additions / removals in HTML tags."""
    matcher = difflib.SequenceMatcher(a=_split_graphemes(old), b=_split_graphemes(new))
    output = []
    for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
        if opcode == "equal":
            output.append(escape(matcher.a[a0:a1]))
        elif opcode == "insert":
            output.extend(_create_markup("ins", matcher.b[b0:b1]))
        elif opcode == "delete":
            output.extend(_create_markup("del", matcher.a[a0:a1]))
        elif opcode == "replace":
            output.extend(_create_markup("del", matcher.a[a0:a1]))
            output.extend(_create_markup("ins", matcher.b[b0:b1]))
        else:
            raise RuntimeError(f"Unexpected opcode {opcode}")
    return "".join(output)
