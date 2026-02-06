"""Validates the structure of an XML document."""

import dataclasses as dc
from enum import StrEnum
import xml.etree.ElementTree as ET

import defusedxml.ElementTree as DET


# Keep in sync with prosemirror-editor.ts::BLOCK_TYPES
class BlockType(StrEnum):
    PARAGRAPH = "p"
    VERSE = "verse"
    FOOTNOTE = "footnote"
    HEADING = "heading"
    TRAILER = "trailer"
    TITLE = "title"
    SUBTITLE = "subtitle"
    IGNORE = "ignore"
    METADATA = "metadata"


# Keep in sync with marks-config.ts::INLINE_MARKS
class InlineType(StrEnum):
    ERROR = "error"
    FIX = "fix"
    SPEAKER = "speaker"
    STAGE = "stage"
    REF = "ref"
    FLAG = "flag"
    CHAYA = "chaya"
    PRAKRIT = "prakrit"
    NOTE = "note"
    ADD = "add"
    ELLIPSIS = "ellipsis"


class TEITag(StrEnum):
    # Structure
    TITLE = "title"
    HEAD = "head"
    TRAILER = "trailer"

    # Blocks
    LG = "lg"
    L = "l"
    P = "p"

    # Drama
    SP = "sp"
    STAGE = "stage"
    SPEAKER = "speaker"

    # Errors
    CHOICE = "choice"
    SEG = "seg"
    SIC = "sic"
    CORR = "corr"
    UNCLEAR = "unclear"
    SUPPLIED = "supplied"

    # Editor annotations
    ADD = "add"
    ELLIPSIS = "ellipsis"

    # References
    REF = "ref"
    NOTE = "note"

    # Page divisions
    PB = "pb"


@dc.dataclass
class ValidationSpec:
    children: set[str] = dc.field(default_factory=set)
    attrib: set[str] = dc.field(default_factory=set)


class ValidationType(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dc.dataclass
class ValidationResult:
    type: ValidationType
    message: str

    @staticmethod
    def error(message: str) -> "ValidationResult":
        return ValidationResult(type=ValidationType.ERROR, message=message)

    @staticmethod
    def warning(message: str) -> "ValidationResult":
        return ValidationResult(type=ValidationType.WARNING, message=message)


CORE_INLINE_TYPES = set(InlineType)
PROOFING_XML_VALIDATION_SPEC = {
    "page": ValidationSpec(children=set(BlockType), attrib=set()),
    BlockType.PARAGRAPH: ValidationSpec(
        children=CORE_INLINE_TYPES,
        attrib={"lang", "text", "n", "merge-next", "merge-text"},
    ),
    BlockType.VERSE: ValidationSpec(
        children=CORE_INLINE_TYPES,
        attrib={"lang", "text", "n", "merge-next", "merge-text"},
    ),
    BlockType.FOOTNOTE: ValidationSpec(
        children=CORE_INLINE_TYPES, attrib={"lang", "text", "mark"}
    ),
    BlockType.HEADING: ValidationSpec(
        children=CORE_INLINE_TYPES, attrib={"lang", "text", "n"}
    ),
    BlockType.TRAILER: ValidationSpec(
        children=CORE_INLINE_TYPES, attrib={"lang", "text", "n"}
    ),
    BlockType.TITLE: ValidationSpec(
        children=CORE_INLINE_TYPES, attrib={"lang", "text", "n"}
    ),
    BlockType.SUBTITLE: ValidationSpec(
        children=CORE_INLINE_TYPES, attrib={"lang", "text", "n"}
    ),
    BlockType.IGNORE: ValidationSpec(
        children=CORE_INLINE_TYPES, attrib={"lang", "text"}
    ),
    BlockType.METADATA: ValidationSpec(children=set(), attrib=set()),
    **{
        tag: ValidationSpec(children=set(InlineType), attrib=set())
        for tag in InlineType
    },
}

# TODO:
# - `fix` is not TEI xml
# - `flag` is not TEI xml
# - `subtitle` is not supported
# - `stage` in `seg` ??? `choice` in `seg` ?
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
INLINE_TEXT = {
    TEITag.CHOICE,
    TEITag.REF,
    TEITag.SUPPLIED,
    TEITag.NOTE,
    TEITag.PB,
    TEITag.ADD,
    TEITag.ELLIPSIS,
    TEITag.UNCLEAR,
}
TEI_XML_VALIDATION_SPEC = {
    TEITag.SP: ValidationSpec(
        children={TEITag.SPEAKER, TEITag.P, TEITag.LG, TEITag.STAGE, "note"},
        attrib={"n"},
    ),
    TEITag.STAGE: ValidationSpec(attrib={"rend"}),
    TEITag.SPEAKER: ValidationSpec(),
    TEITag.LG: ValidationSpec(children={"l", "note", "pb"}, attrib={"n"}),
    TEITag.L: ValidationSpec(children=INLINE_TEXT, attrib=set()),
    TEITag.P: ValidationSpec(
        children=INLINE_TEXT | {TEITag.STAGE},
        attrib={"n"},
    ),
    TEITag.CHOICE: ValidationSpec(
        children={TEITag.SEG, TEITag.CORR, TEITag.SIC}, attrib={"type", "rend"}
    ),
    TEITag.SEG: ValidationSpec(attrib={XML_LANG}),
    TEITag.HEAD: ValidationSpec(attrib={"n"}),
    TEITag.TITLE: ValidationSpec(attrib={"n", "type"}),
    TEITag.TRAILER: ValidationSpec(attrib={"n"}),
    TEITag.REF: ValidationSpec(attrib={"target", "type"}),
    TEITag.NOTE: ValidationSpec(attrib={"type", XML_ID}),
    TEITag.SIC: ValidationSpec(),
    TEITag.CORR: ValidationSpec(),
    TEITag.PB: ValidationSpec(attrib={"n"}),
    TEITag.SUPPLIED: ValidationSpec(),
    TEITag.ADD: ValidationSpec(),
    TEITag.ELLIPSIS: ValidationSpec(),
    TEITag.UNCLEAR: ValidationSpec(),
}


METADATA_FIELDS = {"speaker", "div.title", "div.n"}


def validate_metadata(text: str) -> list[ValidationResult]:
    """Validate metadata block content (one key=value pair per line)."""
    results = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if "=" not in line:
            results.append(
                ValidationResult.error(
                    f"Metadata line {i}: expected 'key=value' format, got '{line}'"
                )
            )
            continue
        key, _, _ = line.partition("=")
        key = key.strip()
        if key not in METADATA_FIELDS:
            results.append(
                ValidationResult.error(
                    f"Metadata line {i}: unknown field '{key}'"
                    f" (allowed: {', '.join(sorted(METADATA_FIELDS))})"
                )
            )
    return results


def validate_xml(
    xml: ET.Element, specs: dict[str, ValidationSpec]
) -> list[ValidationResult]:
    results = []

    def _validate_element(el, path=()):
        tag = el.tag
        current_path = path + (tag,)

        if tag not in specs:
            results.append(
                ValidationResult.error(
                    f"Unknown element '{tag}' at {'/'.join(current_path)}"
                )
            )
            return

        spec = specs[tag]

        for attr in el.attrib:
            if attr not in spec.attrib:
                results.append(
                    ValidationResult.error(
                        f"Unexpected attribute '{attr}' on element '{tag}' at {'/'.join(current_path)}"
                    )
                )

        for child in el:
            if child.tag not in spec.children:
                results.append(
                    ValidationResult.error(
                        f"Unexpected child element '{child.tag}' in '{tag}' at {'/'.join(current_path)}"
                    )
                )
            _validate_element(child, current_path)

    _validate_element(xml)
    return results


def validate_proofing_xml(content: str) -> list[ValidationResult]:
    results = []

    try:
        root = DET.fromstring(content)
    except ET.ParseError as e:
        return [ValidationResult.error(f"XML parse error: {e}")]

    # Root tag should always be "page"
    if root.tag != "page":
        return [ValidationResult.error(f"Root tag must be 'page', got '{root.tag}'")]

    results = validate_xml(root, PROOFING_XML_VALIDATION_SPEC)

    for child in root:
        if child.tag == BlockType.METADATA:
            results.extend(validate_metadata(child.text or ""))

    return results


def validate_tei_xml(xml: ET.Element) -> list[ValidationResult]:
    ret = validate_xml(xml, TEI_XML_VALIDATION_SPEC)
    return ret
