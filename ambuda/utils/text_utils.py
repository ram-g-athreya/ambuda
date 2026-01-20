import dataclasses as dc

from vidyut.lipi import transliterate, Scheme

import ambuda.database as db
from ambuda import queries as q


@dc.dataclass
class TextEntry:
    text: db.Text
    children: list["TextEntry"]

    genre: db.Genre | None
    author: db.Author | None


def create_text_entries() -> list[TextEntry]:
    texts = q.texts()
    mula_texts = []
    child_texts = []
    for text in texts:
        is_mula = text.parent_id is None
        (child_texts, mula_texts)[is_mula].append(text)

    sorted_mula_texts = sorted(
        mula_texts,
        key=lambda x: transliterate(x.title, Scheme.HarvardKyoto, Scheme.Devanagari),
    )
    sorted_child_texts = sorted(
        child_texts,
        key=lambda x: transliterate(x.title, Scheme.HarvardKyoto, Scheme.Devanagari),
    )
    genre_map = {x.id: x for x in q.genres()}
    author_map = {x.id: x for x in q.authors()}

    text_entries = []
    text_entry_map = {}
    for text in sorted_mula_texts:
        assert text.parent_id is None

        genre = genre_map.get(text.genre_id)
        author = author_map.get(text.author_id)
        entry = TextEntry(
            text=text,
            children=[],
            genre=genre,
            author=author,
        )
        text_entries.append(entry)
        text_entry_map[text.id] = entry

    for text in sorted_child_texts:
        assert text.parent_id is not None

        entry = TextEntry(text=text, children=[], genre=None, author=None)
        try:
            parent = text_entry_map[text.parent_id]
            parent.children.append(entry)
        except KeyError:
            pass

    return text_entries


def create_grouped_text_entries() -> dict[str, list[TextEntry]]:
    _d = lambda x: transliterate(x, Scheme.HarvardKyoto, Scheme.Devanagari)

    headings = {
        _d("upaniSat"): _d("vedAH"),
        _d("itihAsaH"): _d("itihAsau"),
        _d("kAvyam"): _d("kAvyAni"),
        _d("stotram"): _d("stotrANi"),
    }

    grouped_entries = {}
    for heading in headings.values():
        grouped_entries[heading] = []
    grouped_entries[_d("anye granthAH")] = []

    for entry in create_text_entries():
        heading = None
        if entry.genre:
            heading = headings.get(entry.genre.name)
        if heading is None:
            heading = _d("anye granthAH")
        grouped_entries[heading].append(entry)
    return grouped_entries
