"""Utilities for exporting texts in various formats."""

import csv
from pathlib import Path
import tempfile
from xml.etree import ElementTree as ET

import defusedxml.ElementTree as DET
import requests
import typst
from flask import current_app
from vidyut.lipi import transliterate, Scheme

import ambuda.database as db
from ambuda.utils.datetime import utc_datetime_timestamp
from ambuda.s3_utils import S3Path
from ambuda import queries as q


EXPORT_DIR = Path(__file__).parent


def font_directory() -> Path:
    """Get a path to our font files, loading from S3 if necessary."""
    temp_dir = Path(tempfile.gettempdir())
    fonts_dir = temp_dir / "ambuda_fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)

    font_path = fonts_dir / "NotoSerifDevanagari.ttf"
    if font_path.exists():
        return fonts_dir

    bucket = current_app.config["S3_BUCKET"]
    try:
        # TODO: variable fonts are not supported well in typst.
        path = S3Path(
            bucket, "assets/fonts/NotoSerifDevanagari-VariableFont_wdth,wght.ttf"
        )
        path.download_file(font_path)
    except Exception as e:
        print(f"Exception while downloading font: {e}")
    return fonts_dir


def create_text_file(text: db.Text, file_path: str) -> None:
    timestamp = utc_datetime_timestamp()

    with open(file_path, "w") as f:
        f.write(f"# {text.title}\n")
        f.write(f"# Exported from ambuda.org on {timestamp}\n\n")

        is_first = True
        for section in text.sections:
            for block in section.blocks:
                if not is_first:
                    f.write("\n\n")
                is_first = False

                f.write(f"# {block.slug}\n")
                xml = DET.fromstring(block.xml)
                for el in xml.iter():
                    if el.tag == "l":
                        el.tail = "\n"
                    el.tag = None
                f.write(ET.tostring(xml, encoding="unicode").strip())


def create_xml_file(text: db.Text, file_path: str) -> None:
    tei = ET.Element("TEI")
    tei.attrib["xmlns"] = "http://www.tei-c.org/ns/1.0"

    # Header
    tei_header = ET.SubElement(tei, "teiHeader")
    file_desc = ET.SubElement(tei_header, "fileDesc")
    title = ET.SubElement(file_desc, "title")
    title.text = text.title
    author = ET.SubElement(file_desc, "author")
    author.text = text.author.name if text.author else "(missing)"

    publication_stmt = ET.SubElement(tei_header, "publicationStmt")
    publisher = ET.SubElement(publication_stmt, "publisher")
    publisher.text = "Ambuda (https://ambuda.org)"
    availability = ET.SubElement(publication_stmt, "availability")
    availability.text = "TODO"

    notes_stmt = ET.SubElement(tei_header, "notesStmt")
    if text.project_id is not None:
        note = ET.SubElement(notes_stmt, "note")
        note.text = (
            "This text has been created by direct export from Ambuda's proofing system."
        )
    else:
        note = ET.SubElement(notes_stmt, "note")
        note.text = (
            "This text has been created by third-party import from another site."
        )

    encoding_desc = ET.SubElement(tei_header, "encodingDesc")
    project_desc = ET.SubElement(encoding_desc, "projectDesc")
    project_desc_p = ET.SubElement(project_desc, "p")
    project_desc_p.text = "Ambuda is an online library of Sanskrit literature."

    # Main text
    _text = ET.SubElement(tei, "text")
    body = ET.SubElement(_text, "body")

    for section in text.sections:
        for block in section.blocks:
            el = DET.fromstring(block.xml)
            body.append(el)

    tree = ET.ElementTree(tei)
    ET.indent(tree, space="  ", level=0)
    tree.write(file_path, xml_declaration=True, encoding="utf-8")


def create_pdf(text: db.Text, file_path: str) -> None:
    timestamp = utc_datetime_timestamp()

    buf = []
    for section in text.sections:
        for block in section.blocks:
            buf.append(f'#text(size: 9pt, fill: rgb("#666666"))[{block.slug}]\n\n')

            xml_el = DET.fromstring(block.xml)
            for el in xml_el.iter():
                if el.tag == "l":
                    el.tail = " \\\n" + (el.tail or "")
                el.tag = None
            content = ET.tostring(xml_el, encoding="unicode").strip()

            buf.append(content)
            buf.append("\n\n")

    content = "".join(buf)

    template_path = Path(__file__).parent.parent / "templates/exports/document.typ"
    with open(template_path, "r") as f:
        template = f.read()

    # Just in case
    text_title = transliterate(text.title, Scheme.HarvardKyoto, Scheme.Devanagari)

    typst_content = template.format(
        title=text_title, timestamp=timestamp, content=content
    )

    fonts_dir = Path(__file__).parent.parent / "static/fonts"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".typ") as typst_file:
        typst_file.write(typst_content)
        typst_file_path = typst_file.name

        font_paths = [font_directory()]
        _, _warnings = typst.compile_with_warnings(
            typst_file_path,
            font_paths=font_paths,
            output=file_path,
        )


def create_tokens(text: db.Text, file_path: str) -> None:
    session = q.get_session()
    tokens = (
        session.query(db.Token)
        .join(db.TextBlock)
        .filter(db.TextBlock.text_id == text.id)
        .order_by(db.Token.block_id, db.Token.order)
        .all()
    )

    if tokens:
        pass

    buf = []
    assert not tokens

    with open(file_path, "w") as f:
        writer = csv.writer(f, delimiter=",")

        session = q.get_session()
        results = (
            session.query(db.BlockParse, db.TextBlock.slug)
            .join(db.TextBlock, db.BlockParse.block_id == db.TextBlock.id)
            .filter(db.BlockParse.text_id == text.id)
            .all()
        )

        for block_parse, block_slug in results:
            for line in block_parse.data.splitlines():
                fields = line.split("\t")
                if len(fields) != 3:
                    continue

                form, base, parse_data = fields
                parse_data = parse_data.replace(",", " ")
                writer.writerow([block_slug, form, base, parse_data])
