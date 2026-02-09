import dataclasses as dc
import xml.etree.ElementTree as ET

import pytest

from ambuda.utils import text_publishing as s


@dc.dataclass
class MockStatus:
    name: str


@dc.dataclass
class MockRevision:
    id: int
    page_id: int
    content: str
    status: MockStatus | None = None


@dc.dataclass
class MockPage:
    revisions: list[MockRevision]


@dc.dataclass
class MockProject:
    pages: list[MockPage]
    page_numbers: str = ""


@dc.dataclass
class MockConfig:
    target: str = "(and)"


@pytest.mark.parametrize(
    "input,expected",
    [
        # Basic usage
        ("<p>foo</p>", "<p>foo</p>"),
        ("<heading>foo</heading>", "<head>foo</head>"),
        ("<title>foo</title>", "<title>foo</title>"),
        ("<trailer>foo</trailer>", "<trailer>foo</trailer>"),
        # Other block types do not have a spec, so skip them for now.
        # <p>
        # <p> joins together text spread across multiple lines.
        ("<p>foo \nbar</p>", "<p>foo bar</p>"),
        ("<p>foo\nbar</p>", "<p>foo bar</p>"),
        ("<p>foo \n bar</p>", "<p>foo bar</p>"),
        # `-` at the end of a line joins words together across lines.
        ("<p>foo-\nbar</p>", "<p>foobar</p>"),
        ("<p>foo-bar\nbiz</p>", "<p>foo-bar biz</p>"),
        # <p> should respect and retain inline marks when joining text.
        ("<p><fix>foo</fix> \n bar</p>", "<p><supplied>foo</supplied> bar</p>"),
        # <lg>
        # <lg> breaks down lines (separated by whitespace) into separate <l> elements.
        ("<verse>foo</verse>", "<lg><l>foo</l></lg>"),
        ("<verse>foo\nbar</verse>", "<lg><l>foo</l><l>bar</l></lg>"),
        ("<verse>foo\nbar\nbiz</verse>", "<lg><l>foo</l><l>bar</l><l>biz</l></lg>"),
        # <lg> should respect and retain inline marks when splitting lines.
        (
            "<verse>f<fix>oo</fix>oo\nbar</verse>",
            "<lg><l>f<supplied>oo</supplied>oo</l><l>bar</l></lg>",
        ),
        # <lg> should respect and retain inline marks at the end of lines too.
        (
            "<verse>f<fix>oo</fix>\nbar</verse>",
            "<lg><l>f<supplied>oo</supplied></l><l>bar</l></lg>",
        ),
        # <lg> should normalize whitespace to some extent.
        (
            "<verse>f<fix>oo</fix> \n bar</verse>",
            "<lg><l>f<supplied>oo</supplied></l><l>bar</l></lg>",
        ),
        # TODO: too hard
        # ("<verse>f<fix>oo\nbar</fix> biz</verse>", "<lg><l>f<supplied>oo</supplied></l><l><supplied>bar</supplied> biz</l></lg>"),
        # <error> and <fix>
        # Error and fix consecutively (despite whitespace) --> sic and corr
        (
            "<p>foo<error>bar</error> <fix>biz</fix> tail</p>",
            "<p>foo<choice><sic>bar</sic><corr>biz</corr></choice> tail</p>",
        ),
        # Invariant to order.
        (
            "<p>foo<fix>biz</fix> <error>bar</error></p>",
            "<p>foo<choice><sic>bar</sic><corr>biz</corr></choice></p>",
        ),
        # Error alone --> sic, with empty corr
        (
            "<p>foo<error>bar</error> tail</p>",
            "<p>foo<choice><sic>bar</sic><corr /></choice> tail</p>",
        ),
        # Fix alone --> supplied (no corr)
        ("<p>foo<fix>bar</fix></p>", "<p>foo<supplied>bar</supplied></p>"),
        # Separate fix and error -- don't group into a single choice
        (
            "<p>foo<error>bar</error> biz <fix>baf</fix> tail</p>",
            "<p>foo<choice><sic>bar</sic><corr /></choice> biz <supplied>baf</supplied> tail</p>",
        ),
        # <chaya>
        (
            "<p>aoeu<x>foo</x><chaya>asdf<y>bar</y></chaya></p>",
            '<p><choice type="chaya"><seg xml:lang="pra">aoeu<x>foo</x></seg><seg xml:lang="sa">asdf<y>bar</y></seg></choice></p>',
        ),
        # <speaker> converts the block type to <sp>. <speaker> is yanked out of the block into <sp>,
        # preserving element order. The old block type is appended as a child to <sp>.
        ("<p><speaker>foo</speaker></p>", "<sp><speaker>foo</speaker></sp>"),
        (
            "<p><speaker>foo</speaker>bar-\nbiz</p>",
            "<sp><speaker>foo</speaker><p>barbiz</p></sp>",
        ),
        # <flag> --> <unclear>
        ("<p><flag>foo</flag></p>", "<p><unclear>foo</unclear></p>"),
        # No content --> don't preserve the <p>.
        ("<p> <speaker>foo</speaker> </p>", "<sp><speaker>foo</speaker></sp>"),
        (
            "<verse><speaker>foo</speaker>bar</verse>",
            "<sp><speaker>foo</speaker><lg><l>bar</l></lg></sp>",
        ),
    ],
)
def test_rewrite_block_to_tei_xml(input, expected):
    xml = ET.fromstring(input)
    s._rewrite_block_to_tei_xml(xml, 42)
    actual = ET.tostring(xml)
    assert expected.encode("utf-8") == actual


@pytest.mark.parametrize(
    "input,expected",
    [
        ("<p><speaker>foo</speaker></p>", "<sp><speaker>foo</speaker></sp>"),
        ("<p><speaker>foo - </speaker></p>", "<sp><speaker>foo</speaker></sp>"),
        ("<p><speaker> foo -– </speaker></p>", "<sp><speaker>foo</speaker></sp>"),
    ],
)
def test_rewrite_block_to_tei_xml__speaker(input, expected):
    xml = ET.fromstring(input)
    s._rewrite_block_to_tei_xml(xml, 42)
    actual = ET.tostring(xml)
    assert expected.encode("utf-8") == actual


@pytest.mark.parametrize(
    "input,expected",
    [
        ("<p><stage>foo</stage></p>", "<p><stage>foo</stage></p>"),
        ("<p><stage>(foo)</stage></p>", '<p><stage rend="parentheses">foo</stage></p>'),
        (
            "<p><stage> ( foo ) </stage></p>",
            '<p><stage rend="parentheses">foo</stage></p>',
        ),
    ],
)
def test_rewrite_block_to_tei_xml__stage(input, expected):
    xml = ET.fromstring(input)
    s._rewrite_block_to_tei_xml(xml, 42)
    actual = ET.tostring(xml)
    assert expected.encode("utf-8") == actual


@pytest.mark.parametrize(
    "input,expected",
    [
        (
            "<p><chaya>foo</chaya></p>",
            '<p><choice type="chaya"><seg xml:lang="pra" /><seg xml:lang="sa">foo</seg></choice></p>',
        ),
        (
            "<p><chaya>[foo]</chaya></p>",
            '<p><choice type="chaya"><seg xml:lang="pra" /><seg xml:lang="sa" rend="brackets">foo</seg></choice></p>',
        ),
        (
            "<p><chaya> [ foo ] </chaya></p>",
            '<p><choice type="chaya"><seg xml:lang="pra" /><seg xml:lang="sa" rend="brackets">foo</seg></choice></p>',
        ),
    ],
)
def test_rewrite_block_to_tei_xml__chaya(input, expected):
    xml = ET.fromstring(input)
    s._rewrite_block_to_tei_xml(xml, 42)
    actual = ET.tostring(xml)
    assert expected.encode("utf-8") == actual


def _test_create_tei_document(input, expected):
    """Helper function for testing _create_tei_sections_and_blocks."""
    pages = []
    for i, page_xml in enumerate(input):
        revision = MockRevision(id=i, page_id=i, content=page_xml)
        pages.append(MockPage(revisions=[revision]))

    project = MockProject(pages=pages)
    config = MockConfig()

    conversion = s._create_tei_sections_and_blocks(project, config)
    tei_blocks = conversion.sections[0].blocks
    assert tei_blocks == expected


def test_create_tei_document__paragraph():
    _test_create_tei_document(
        ['<page><p n="1">अ</p></page>'],
        [s.TEIBlock(xml='<p n="1">अ</p>', slug="1", page_id=0)],
    )


def test_create_tei_document__paragraph_with_concatenation():
    _test_create_tei_document(
        [
            '<page><p n="1" merge-next="true">अ</p></page>',
            '<page><p n="1">a</p></page>',
        ],
        [s.TEIBlock(xml='<p n="1">अ<pb n="-" />a</p>', slug="1", page_id=0)],
    )


def test_create_tei_document__paragraph_with_speaker():
    _test_create_tei_document(
        ['<page><p n="1"><speaker>foo</speaker> अ</p></page>'],
        [
            s.TEIBlock(
                xml='<sp n="sp1"><speaker>foo</speaker><p n="1">अ</p></sp>',
                slug="sp1",
                page_id=0,
            )
        ],
    )


def test_create_tei_document__paragraph_with_speaker_and_concatenation():
    _test_create_tei_document(
        [
            '<page><p n="1" merge-next="true"><speaker>foo</speaker> अ</p></page>',
            '<page><p n="1">a</p></page>',
        ],
        [
            s.TEIBlock(
                xml='<sp n="sp1"><speaker>foo</speaker><p n="1">अ<pb n="-" />a</p></sp>',
                slug="sp1",
                page_id=0,
            ),
        ],
    )


def test_create_tei_document__verse():
    _test_create_tei_document(
        ['<page><verse n="1">अ</verse></page>'],
        [s.TEIBlock(xml='<lg n="1"><l>अ</l></lg>', slug="1", page_id=0)],
    )


def test_create_tei_document__verse_with_concatenation():
    _test_create_tei_document(
        [
            '<page><verse n="1" merge-next="true">अ</verse></page>',
            '<page><verse n="1">a</verse></page>',
        ],
        [
            s.TEIBlock(
                xml='<lg n="1"><l>अ</l><pb n="-" /><l>a</l></lg>', slug="1", page_id=0
            )
        ],
    )


def test_create_tei_document__verse_with_fix_inline_element():
    _test_create_tei_document(
        ['<page><verse n="1">अ<fix>क</fix>ख</verse></page>'],
        [
            s.TEIBlock(
                xml='<lg n="1"><l>अ<supplied>क</supplied>ख</l></lg>',
                slug="1",
                page_id=0,
            )
        ],
    )


def test_create_tei_document__paragraph_with_fix_inline_element():
    _test_create_tei_document(
        ['<page><p n="1">अ<fix>क</fix>ख</p></page>'],
        [
            s.TEIBlock(
                xml='<p n="1">अ<supplied>क</supplied>ख</p>', slug="1", page_id=0
            ),
        ],
    )


def test_create_tei_document__autoincrement():
    _test_create_tei_document(
        ['<page><p n="1">a</p><p>b</p><p>c</p></page>'],
        [
            s.TEIBlock(xml='<p n="1">a</p>', slug="1", page_id=0),
            s.TEIBlock(xml='<p n="2">b</p>', slug="2", page_id=0),
            s.TEIBlock(xml='<p n="3">c</p>', slug="3", page_id=0),
        ],
    )


def test_create_tei_document__autoincrement_with_dot_prefix():
    _test_create_tei_document(
        ['<page><p n="1.1">a</p><p>b</p><p>c</p></page>'],
        [
            s.TEIBlock(xml='<p n="1.1">a</p>', slug="1.1", page_id=0),
            s.TEIBlock(xml='<p n="1.2">b</p>', slug="1.2", page_id=0),
            s.TEIBlock(xml='<p n="1.3">c</p>', slug="1.3", page_id=0),
        ],
    )


def test_create_tei_document__autoincrement_with_non_dot_prefix():
    _test_create_tei_document(
        ['<page><p n="p1">a</p><p>b</p><p>c</p></page>'],
        [
            s.TEIBlock(xml='<p n="p1">a</p>', slug="p1", page_id=0),
            s.TEIBlock(xml='<p n="p2">b</p>', slug="p2", page_id=0),
            s.TEIBlock(xml='<p n="p3">c</p>', slug="p3", page_id=0),
        ],
    )


def test_create_tei_document__autoincrement_with_weird_prefix():
    _test_create_tei_document(
        ['<page><p n="foo">a</p><p>b</p><p>c</p></page>'],
        [
            s.TEIBlock(xml='<p n="foo">a</p>', slug="foo", page_id=0),
            s.TEIBlock(xml='<p n="foo2">b</p>', slug="foo2", page_id=0),
            s.TEIBlock(xml='<p n="foo3">c</p>', slug="foo3", page_id=0),
        ],
    )


def test_create_tei_document__autoincrement_with_mixed_types():
    _test_create_tei_document(
        [
            '<page><p n="p1">a</p><verse n="1">A</verse></page>',
            "<page><p>b</p><verse>B</verse><p>c</p></page>",
        ],
        [
            s.TEIBlock(xml='<p n="p1">a</p>', slug="p1", page_id=0),
            s.TEIBlock(xml='<lg n="1"><l>A</l></lg>', slug="1", page_id=0),
            s.TEIBlock(xml='<p n="p2">b</p>', slug="p2", page_id=1),
            s.TEIBlock(xml='<lg n="2"><l>B</l></lg>', slug="2", page_id=1),
            s.TEIBlock(xml='<p n="p3">c</p>', slug="p3", page_id=1),
        ],
    )


def _make_block(image_number, block_index, page_xml_str):
    page_xml = ET.fromstring(page_xml_str)
    revision = MockRevision(id=1, page_id=1, content=page_xml_str)
    return s.IndexedBlock(
        revision=revision,
        image_number=image_number,
        block_index=block_index,
        page_xml=page_xml,
    )


def test_filter_parse__rejects_deeply_nested_sexp():
    deeply_nested = "(" * 50 + "and" + ")" * 50
    with pytest.raises(ValueError, match="levels deep"):
        s.Filter(deeply_nested)


def test_filter_parse__rejects_missing_open_paren():
    with pytest.raises(ValueError, match="must start with"):
        s.Filter("image 1")


def test_filter_parse__rejects_missing_close_paren():
    with pytest.raises(ValueError, match="Missing closing parenthesis"):
        s.Filter("(image 1")


def test_filter_matches__image_single():
    f = s.Filter("(image 3)")
    block2 = _make_block(2, 0, "<page><p>a</p></page>")
    block3 = _make_block(3, 0, "<page><p>a</p></page>")
    block4 = _make_block(4, 0, "<page><p>a</p></page>")
    assert not f.matches(block2)
    assert f.matches(block3)
    assert not f.matches(block4)


def test_filter_matches__image_range():
    f = s.Filter("(image 2 4)")
    block1 = _make_block(1, 0, "<page><p>a</p></page>")
    block2 = _make_block(2, 0, "<page><p>a</p></page>")
    block3 = _make_block(3, 0, "<page><p>a</p></page>")
    block4 = _make_block(4, 0, "<page><p>a</p></page>")
    block5 = _make_block(5, 0, "<page><p>a</p></page>")
    assert not f.matches(block1)
    assert f.matches(block2)
    assert f.matches(block3)
    assert f.matches(block4)
    assert not f.matches(block5)


def test_filter_matches__page_alias():
    f = s.Filter("(page 3)")
    block3 = _make_block(3, 0, "<page><p>a</p></page>")
    assert f.matches(block3)


def test_filter_matches__label():
    f = s.Filter("(label foo)")
    block_match = _make_block(1, 0, '<page><p text="foo">a</p></page>')
    block_no_match = _make_block(1, 0, '<page><p text="bar">a</p></page>')
    block_no_attr = _make_block(1, 0, "<page><p>a</p></page>")
    assert f.matches(block_match)
    assert not f.matches(block_no_match)
    assert not f.matches(block_no_attr)


def test_filter_matches__label_second_block():
    f = s.Filter("(label bar)")
    block = _make_block(1, 1, '<page><p text="foo">a</p><p text="bar">b</p></page>')
    assert f.matches(block)


def test_filter_matches__tag():
    f = s.Filter("(tag p)")
    block_p = _make_block(1, 0, "<page><p>a</p></page>")
    block_verse = _make_block(1, 0, "<page><verse>a</verse></page>")
    assert f.matches(block_p)
    assert not f.matches(block_verse)


def test_filter_matches__and():
    f = s.Filter("(and (image 2 4) (tag p))")
    block_match = _make_block(3, 0, "<page><p>a</p></page>")
    block_wrong_tag = _make_block(3, 0, "<page><verse>a</verse></page>")
    block_wrong_image = _make_block(1, 0, "<page><p>a</p></page>")
    assert f.matches(block_match)
    assert not f.matches(block_wrong_tag)
    assert not f.matches(block_wrong_image)


def test_filter_matches__or():
    f = s.Filter("(or (image 1) (image 3))")
    block1 = _make_block(1, 0, "<page><p>a</p></page>")
    block2 = _make_block(2, 0, "<page><p>a</p></page>")
    block3 = _make_block(3, 0, "<page><p>a</p></page>")
    assert f.matches(block1)
    assert not f.matches(block2)
    assert f.matches(block3)


def test_filter_matches__not():
    f = s.Filter("(not (image 2))")
    block1 = _make_block(1, 0, "<page><p>a</p></page>")
    block2 = _make_block(2, 0, "<page><p>a</p></page>")
    block3 = _make_block(3, 0, "<page><p>a</p></page>")
    assert f.matches(block1)
    assert not f.matches(block2)
    assert f.matches(block3)


def test_filter_matches__empty_and():
    f = s.Filter("(and)")
    block = _make_block(1, 0, "<page><p>a</p></page>")
    assert f.matches(block)


def test_filter_matches__image_single_with_label():
    f = s.Filter("(image 3:foo)")
    page = '<page><p text="foo">a</p><p text="bar">b</p></page>'
    assert f.matches(_make_block(3, 0, page))
    assert not f.matches(_make_block(3, 1, page))
    assert not f.matches(_make_block(2, 0, '<page><p text="foo">a</p></page>'))


def test_filter_matches__image_range_with_labels():
    f = s.Filter("(image 2:start 4:end)")
    assert not f.matches(_make_block(1, 0, '<page><p text="x">a</p></page>'))
    page2 = (
        '<page><p text="before">a</p><p text="start">b</p><p text="after">c</p></page>'
    )
    assert not f.matches(_make_block(2, 0, page2))
    assert f.matches(_make_block(2, 1, page2))
    assert f.matches(_make_block(2, 2, page2))
    assert f.matches(_make_block(3, 0, "<page><p>a</p></page>"))
    page4 = '<page><p text="end">a</p><p text="after">b</p></page>'
    assert f.matches(_make_block(4, 0, page4))
    assert not f.matches(_make_block(4, 1, page4))
    assert not f.matches(_make_block(5, 0, "<page><p>a</p></page>"))


def test_filter_matches__image_label_start_plain_end():
    f = s.Filter("(image 2:mid 4)")
    page2 = '<page><p text="before">a</p><p text="mid">b</p></page>'
    assert not f.matches(_make_block(2, 0, page2))
    assert f.matches(_make_block(2, 1, page2))
    assert f.matches(_make_block(4, 0, "<page><p>a</p></page>"))


def test_filter_matches__image_plain_start_label_end():
    f = s.Filter("(image 2 4:mid)")
    assert f.matches(_make_block(2, 0, "<page><p>a</p></page>"))
    page4 = '<page><p text="mid">a</p><p text="after">b</p></page>'
    assert f.matches(_make_block(4, 0, page4))
    assert not f.matches(_make_block(4, 1, page4))


def test_filter_matches__image_label_not_found():
    f = s.Filter("(image 3:nonexistent)")
    block = _make_block(3, 0, '<page><p text="other">a</p></page>')
    assert not f.matches(block)


def test_filter_matches__image_label_picks_first():
    f = s.Filter("(image 3:dup)")
    page = '<page><p text="dup">a</p><p text="dup">b</p><p>c</p></page>'
    assert f.matches(_make_block(3, 0, page))
    assert not f.matches(_make_block(3, 1, page))
    assert not f.matches(_make_block(3, 2, page))
