import xml.etree.ElementTree as ET

import pytest

from ambuda.utils import structuring as s


P = s.ProofPage
B = s.ProofBlock


@pytest.mark.parametrize(
    "input,expected",
    [
        ("<p>test</p>", "test"),
        ("<p>test <a>foo</a></p>", "test <a>foo</a>"),
        ("<p>test <a>foo</a> bar</p>", "test <a>foo</a> bar"),
        ("<p><a>foo</a> bar</p>", "<a>foo</a> bar"),
        ("<p><a>foo</a> <b>bar</b></p>", "<a>foo</a> <b>bar</b>"),
        # Unicode
        ("<p>अ <a>अ</a> अ</p>", "अ <a>अ</a> अ"),
    ],
)
def test_inner_xml(input, expected):
    assert s._inner_xml(ET.fromstring(input)) == expected


@pytest.mark.parametrize(
    "input,expected",
    [
        ("<page></page>", P(id=0, blocks=[])),
        (
            "<page><verse>अ</verse></page>",
            P(id=0, blocks=[B(type="verse", content="अ")]),
        ),
        (
            "<page><p>अ</p></page>",
            P(id=0, blocks=[B(type="p", content="अ")]),
        ),
        (
            "<page><p>अ<b>अ</b></p></page>",
            P(id=0, blocks=[B(type="p", content="अ<b>अ</b>")]),
        ),
        (
            '<page><p merge-next="true">अ</p></page>',
            P(id=0, blocks=[B(type="p", content="अ", merge_next=True)]),
        ),
        (
            '<page><p merge-next="false">अ</p></page>',
            P(id=0, blocks=[B(type="p", content="अ", merge_next=False)]),
        ),
        # Legacy behavior
        (
            '<page><p merge-text="true">अ</p></page>',
            P(id=0, blocks=[B(type="p", content="अ", merge_next=True)]),
        ),
    ],
)
def test_from_xml_string(input, expected):
    assert s.ProofPage._from_xml_string(input, 0) == expected


def test_from_content_and_page_id():
    text = """
    अ

    क<error></error><fix>ख</fix>ग

    अ ।
    क ॥

    [^1] क
    """
    text = "\n".join(x.strip() for x in text.splitlines())
    assert s.ProofPage.from_content_and_page_id(text, 0) == P(
        id=0,
        blocks=[
            B(type="p", content="अ", lang="sa"),
            B(type="p", content="क<error></error><fix>ख</fix>ग", lang="sa"),
            B(type="verse", content="अ ।\nक ॥", lang="sa"),
            B(type="footnote", content="क", lang="sa", mark="1"),
        ],
    )


@pytest.mark.parametrize(
    "input,expected",
    [
        (
            P(id=0, blocks=[B(type="p", content="अ", n="1")]),
            s.TEIBlock(xml='<p n="1">अ</p>', slug="1", page_id=0),
        ),
        (
            P(id=0, blocks=[B(type="p", content="अ<fix>क</fix>ख", n="1")]),
            s.TEIBlock(xml='<p n="1">अ<corr>क</corr>ख</p>', slug="1", page_id=0),
        ),
        (
            P(
                id=0,
                blocks=[
                    B(
                        type="verse",
                        content="अ<fix>क</fix>ख",
                        n="1",
                    )
                ],
            ),
            s.TEIBlock(
                xml='<lg n="1"><l>अ<corr>क</corr>ख</l></lg>', slug="1", page_id=0
            ),
        ),
    ],
)
def test_to_tei_document(input, expected):
    tei_doc, _errors = s.ProofProject(pages=[input]).to_tei_document(None, [])
    tei_block = tei_doc.sections[0].blocks[0]
    assert tei_block == expected
