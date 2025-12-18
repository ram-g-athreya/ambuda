import dataclasses as dc
import re
from typing import Callable
import xml.etree.ElementTree as ET

import defusedxml.ElementTree as DET
from vidyut.lipi import transliterate, Scheme

import ambuda.database as db

# pass, fail, warning


@dc.dataclass
class ValidationResult:
    text: str
    num_ok: int
    num_total: int


@dc.dataclass
class ValidationReport:
    results: list[ValidationResult]


@dc.dataclass
class Rule:
    desc: str
    fn: Callable
    scope: str

    def validate(self, doc: ET.Element):
        assert self.scope in {"document", "block", "verse"}
        num_total = 0
        num_ok = 0
        if self.scope == "block":
            for block in _iter_blocks(doc):
                num_total += 1
                num_ok += 1 if self.fn(block) else 0
        elif self.scope == "verse":
            for block in _iter_blocks(doc):
                if block.tag != "lg":
                    continue
                num_total += 1
                num_ok += 1 if self.fn(block) else 0
        else:
            num_total = 1
            num_ok = 1 if self.fn(doc) else 0
        return ValidationResult(text=self.desc, num_ok=num_ok, num_total=num_total)


def validation_rule(desc: str, scope: str = "document"):
    def _inner(fn: Callable):
        return Rule(desc=desc, fn=fn, scope=scope)

    return _inner


def _iter_blocks(xml: ET.Element):
    for div in xml.findall("./div"):
        for block in div:
            yield block


@validation_rule(desc="Blocks have unique identifiers")
def validate_all_blocks_have_unique_n(xml: ET.Element) -> bool:
    seen = set()
    for block in _iter_blocks(xml):
        n = block.attrib.get("n")
        if n:
            if n in seen:
                return False
            seen.add(n)
    return True


@validation_rule(desc="XML is well-formed", scope="block")
def validate_xml_is_well_formed(block: ET.Element) -> bool:
    if block.tag not in {"div", "p", "lg", "head"}:
        return False

    if block.tag == "lg":
        if any(x.tag != "l" for x in block.findall("./")):
            return False

    for el in block.findall("./"):
        if el.tag == "l":
            if block.tag != "lg":
                return False
        elif el.tag not in {"sic", "corr"}:
            return False
    return True


@validation_rule(desc="Sanskrit text is well-formed", scope="block")
def validate_all_sanskrit_text_is_well_formed(block: ET.Element) -> bool:
    # Sanskrit text in Devanagari is expected to match this regex.
    RE_DEVA = r"[\u0900-\u097F ]*"
    for el in block.iter():
        text_ok = re.match(RE_DEVA, el.text or "")
        tail_ok = re.match(RE_DEVA, el.tail or "")
        if not text_ok or not tail_ok:
            return False
    return True


RULES = [
    validate_all_blocks_have_unique_n,
    validate_xml_is_well_formed,
    validate_all_sanskrit_text_is_well_formed,
]


def validate(text: db.Text) -> ValidationReport:
    doc = ET.Element("doc")
    for section in text.sections:
        section_div = ET.SubElement(doc, "div")
        for block in section.blocks:
            el = DET.fromstring(block.xml)
            section_div.append(el)

    results = [rule.validate(doc) for rule in RULES]

    return ValidationReport(results=results)
