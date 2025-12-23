"""Utilities for exporting texts in various formats."""

import csv
import tempfile
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Callable
from lxml import etree
from xml.etree import ElementTree as ET

import defusedxml.ElementTree as DET
import requests
import typst
from flask import current_app
from pydantic import BaseModel
from vidyut.lipi import transliterate, Scheme

import ambuda.database as db
from ambuda.utils.datetime import utc_datetime_timestamp
from ambuda.s3_utils import S3Path
from ambuda import queries as q


EXPORT_DIR = Path(__file__).parent


def font_directory() -> Path:
    """Get a path to our font files, loading from S3 if necessary."""
    log = current_app.logger

    temp_dir = Path(tempfile.gettempdir())
    fonts_dir = temp_dir / "ambuda_fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)

    font_path = fonts_dir / "NotoSerifDevanagari.ttf"
    if font_path.exists():
        log.info(f"Font path exists: {font_path}")
        return fonts_dir

    bucket = current_app.config["S3_BUCKET"]
    try:
        # TODO: variable fonts are not supported well in typst.
        path = S3Path(
            bucket, "assets/fonts/NotoSerifDevanagari-VariableFont_wdth,wght.ttf"
        )
        log.info(f"Downloading font from S3: {path.path}")
        path.download_file(font_path)
    except Exception as e:
        log.error(f"Exception while downloading font: {e}")
    return fonts_dir


def create_xml_file(text: db.Text, file_path: str) -> None:
    """Create a TEI XML file from the given path.

    TEI XML is our canonical file export format from which all other exports are derived.
    It contains structured text data and rich metadata.
    """
    with etree.xmlfile(file_path, encoding="utf-8") as xf:
        xf.write_declaration()

        with xf.element("TEI", xmlns="http://www.tei-c.org/ns/1.0"):
            with xf.element("teiHeader"):
                with xf.element("fileDesc"):
                    with xf.element("title"):
                        xf.write(text.title)
                    with xf.element("author"):
                        xf.write(text.author.name if text.author else "(missing)")

                with xf.element("publicationStmt"):
                    with xf.element("publisher"):
                        xf.write("Ambuda (https://ambuda.org)")
                    with xf.element("availability"):
                        xf.write("TODO")

                with xf.element("notesStmt"):
                    with xf.element("note"):
                        if text.project_id is not None:
                            xf.write(
                                "This text has been created by direct export from Ambuda's proofing system."
                            )
                        else:
                            xf.write(
                                "This text has been created by third-party import from another site."
                            )

                with xf.element("encodingDesc"):
                    with xf.element("projectDesc"):
                        with xf.element("p"):
                            xf.write(
                                "Ambuda is an online library of Sanskrit literature."
                            )

            # Main text
            session = q.get_session()
            with xf.element("text"):
                with xf.element("body"):
                    for section in text.sections:
                        for block in section.blocks:
                            el = etree.fromstring(block.xml)
                            el.set("n", block.slug)
                            xf.write(el)
                        session.expire(section)


def create_plain_text(text: db.Text, file_path: str) -> None:
    timestamp = utc_datetime_timestamp()

    txt_path = Path(file_path)
    xml_path = txt_path.parent / f"{text.slug}.xml"

    if not xml_path.exists():
        raise FileNotFoundError(
            f"XML file not found at {xml_path}. "
            "XML must be generated before plain text export."
        )

    with open(file_path, "w") as f:
        f.write(f"# {text.title}\n")
        f.write(f"# Exported from ambuda.org on {timestamp}\n\n")

        is_first = True
        for event, elem in etree.iterparse(str(xml_path), events=("end",)):
            parent = elem.getparent()
            if parent is not None and parent.tag == "{http://www.tei-c.org/ns/1.0}body":
                slug = elem.get("n")
                if slug:
                    if not is_first:
                        f.write("\n\n")
                    is_first = False

                    f.write(f"# {slug}\n")

                    elem_str = etree.tostring(elem, encoding="unicode")
                    xml = ET.fromstring(elem_str)
                    for el in xml.iter():
                        if el.tag == "l":
                            el.tail = "\n"
                        el.tag = None
                    f.write(ET.tostring(xml, encoding="unicode").strip())

                    elem.clear()
                    while elem.getprevious() is not None:
                        del elem.getparent()[0]


def create_pdf(text: db.Text, file_path: str) -> None:
    log = current_app.logger
    timestamp = utc_datetime_timestamp()

    pdf_path = Path(file_path)
    xml_path = pdf_path.parent / f"{text.slug}.xml"

    if not xml_path.exists():
        raise FileNotFoundError(
            f"XML file not found at {xml_path}. "
            "XML must be generated before PDF export."
        )

    template_path = Path(__file__).parent.parent / "templates/exports/document.typ"
    with open(template_path, "r") as f:
        template = f.read()

    # Just in case
    text_title = transliterate(text.title, Scheme.HarvardKyoto, Scheme.Devanagari)

    parts = template.split("{content}")
    header = parts[0].format(title=text_title, timestamp=timestamp)
    footer = parts[1] if len(parts) > 1 else ""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".typ", delete=False
    ) as typst_file:
        temp_typst_path = typst_file.name

        typst_file.write(header)

        for event, elem in etree.iterparse(str(xml_path), events=("end",)):
            parent = elem.getparent()
            if parent is not None and parent.tag == "{http://www.tei-c.org/ns/1.0}body":
                slug = elem.get("n")
                if slug is not None:
                    typst_file.write(
                        f'#text(size: 9pt, fill: rgb("#666666"))[{slug}]\n\n'
                    )

                    elem_str = etree.tostring(elem, encoding="unicode")
                    elem_copy = ET.fromstring(elem_str)
                    for el in elem_copy.iter():
                        if el.tag == "l":
                            el.tail = " \\\n" + (el.tail or "")
                        el.tag = None
                    content = ET.tostring(elem_copy, encoding="unicode").strip()

                    # Escape Typst special characters
                    content = content.replace("*", r"\*")

                    typst_file.write("#sa[\n")
                    typst_file.write(content)
                    typst_file.write("\n]\n\n")

                    elem.clear()
                    while elem.getprevious() is not None:
                        del elem.getparent()[0]

        typst_file.write(footer)

    try:
        font_paths = [font_directory()]
        _, warnings = typst.compile_with_warnings(
            temp_typst_path,
            font_paths=font_paths,
            output=file_path,
        )
        for warning in warnings:
            log.info(f"Typst warning: {warning.message}")
            log.info(f"Typst trace: {warning.trace}")
    finally:
        if Path(temp_typst_path).exists():
            Path(temp_typst_path).unlink()


def create_tokens(text: db.Text, file_path: str) -> None:
    session = q.get_session()

    with open(file_path, "w") as f:
        writer = csv.writer(f, delimiter=",")

        results = (
            session.query(db.BlockParse, db.TextBlock.slug)
            .join(db.TextBlock, db.BlockParse.block_id == db.TextBlock.id)
            .filter(db.BlockParse.text_id == text.id)
            .yield_per(1000)
        )

        for block_parse, block_slug in results:
            for line in block_parse.data.splitlines():
                fields = line.split("\t")
                if len(fields) != 3:
                    continue

                form, base, parse_data = fields
                parse_data = parse_data.replace(",", " ")
                writer.writerow([block_slug, form, base, parse_data])

            session.expire(block_parse)


class ExportType(StrEnum):
    XML = "xml"
    PLAIN_TEXT = "plain-text"
    PDF = "pdf"
    TOKENS = "tokens"


class ExportConfig(BaseModel):
    label: str
    type: ExportType
    fn: Callable[[db.Text, str], None]
    slug_pattern: str
    mime_type: str

    def slug(self, text: db.Text) -> str:
        return self.slug_pattern.format(text.slug)

    @cached_property
    def suffix(self) -> str:
        return self.slug_pattern.format("")

    def matches(self, filename: str) -> bool:
        return filename.endswith(self.suffix)

    def write_to_local_file(self, text: db.Text, path: Path):
        self.fn(text, str(path))


EXPORTS = [
    ExportConfig(
        label="XML",
        type=ExportType.XML,
        slug_pattern="{}.xml",
        mime_type="application/xml",
        fn=create_xml_file,
    ),
    ExportConfig(
        label="Plain text",
        type=ExportType.PLAIN_TEXT,
        slug_pattern="{}.txt",
        mime_type="text/csv",
        fn=create_plain_text,
    ),
    ExportConfig(
        label="PDF (Devanagari)",
        type=ExportType.PDF,
        slug_pattern="{}-devanagari.pdf",
        mime_type="application/pdf",
        fn=create_pdf,
    ),
    ExportConfig(
        label="Token data (CSV)",
        type=ExportType.TOKENS,
        slug_pattern="{}-tokens.csv",
        mime_type="text/csv",
        fn=create_tokens,
    ),
]
