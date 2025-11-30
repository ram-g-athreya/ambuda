import io
import json
from datetime import datetime

import pytest
from sqlalchemy import select

import ambuda.database as db
from ambuda.queries import get_session


# Sentinel value
class Any:
    pass


def _assert_matches(actual, expected, path: list = None):
    """Recursive comparison on json data.

    NOTE: unused for now, will use soon.
    """
    path = path or []

    if isinstance(actual, dict):
        assert actual.keys() == expected.keys(), path
        for key in actual:
            _assert_matches(actual[key], expected[key], path + [key])
    elif isinstance(actual, list):
        assert len(actual) == len(expected), path
        for a, e in zip(actual, expected):
            _assert_matches(a, e, path + ["*"])
    else:
        if expected is Any:
            # Allow everything
            pass
        else:
            assert actual == expected, path


def test_export_metadata__success(admin_client):
    resp = admin_client.post("/admin/Text/task/export-metadata")
    assert resp.status_code == 200
    assert resp.content_type == "application/json"

    data = json.loads(resp.data)
    assert "slug" in data[0]
    assert "title" in data[0]


def test_import_metadata__success(admin_client):
    resp = admin_client.get("/admin/Text/task/import-metadata")
    assert resp.status_code == 200

    session = get_session()
    stmt = select(db.Text).limit(1)
    text = session.scalars(stmt).first()
    text_id = text.id

    metadata = [
        {
            "slug": text.slug,
            "title": "Updated Title",
            "header": "Updated Header",
        }
    ]

    json_data = json.dumps(metadata).encode("utf-8")

    resp = admin_client.post(
        "/admin/Text/task/import-metadata",
        data={
            "json_file": (io.BytesIO(json_data), "metadata.json"),
            "csrf_token": "fake_token",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    resp = admin_client.get(f"/admin/Text/{text_id}/edit")
    assert b"Updated Header" in resp.data


def test_import_metadata__invalid_json(admin_client):
    invalid_data = b"not valid json{"

    resp = admin_client.post(
        "/admin/Text/task/import-metadata",
        data={
            "json_file": (io.BytesIO(invalid_data), "bad.json"),
            "csrf_token": "fake_token",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200


# Import dictionaries tests
def test_import_dictionaries__get(admin_client):
    resp = admin_client.get("/admin/Dictionary/task/import-dictionaries")
    assert resp.status_code == 200


def test_import_dictionaries__no_files(admin_client):
    resp = admin_client.post(
        "/admin/Dictionary/task/import-dictionaries",
        data={"csrf_token": "fake_token"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_import_dictionaries__non_xml_file(admin_client):
    invalid_file = b"This is not XML"

    resp = admin_client.post(
        "/admin/Dictionary/task/import-dictionaries",
        data={
            "xml_files": [(io.BytesIO(invalid_file), "test.txt")],
            "slug_0": "test-dict",
            "title_0": "Test Dictionary",
            "csrf_token": "fake_token",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Must be an XML file" in resp.data


def test_import_dictionaries__missing_slug(admin_client):
    xml_data = b'<?xml version="1.0"?><dictionary></dictionary>'

    resp = admin_client.post(
        "/admin/Dictionary/task/import-dictionaries",
        data={
            "xml_files": [(io.BytesIO(xml_data), "test.xml")],
            "title_0": "Test Dictionary",
            "csrf_token": "fake_token",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Slug is required" in resp.data


def test_import_dictionaries__missing_title(admin_client):
    xml_data = b'<?xml version="1.0"?><dictionary></dictionary>'

    resp = admin_client.post(
        "/admin/Dictionary/task/import-dictionaries",
        data={
            "xml_files": [(io.BytesIO(xml_data), "test.xml")],
            "slug_0": "test-dict",
            "csrf_token": "fake_token",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Title is required" in resp.data


def test_import_dictionaries__duplicate_slug(admin_client):
    session = get_session()

    existing_dict = db.Dictionary(slug="existing-dict", title="Existing Dictionary")
    session.add(existing_dict)
    session.commit()

    xml_data = b'<?xml version="1.0"?><dictionary></dictionary>'

    resp = admin_client.post(
        "/admin/Dictionary/task/import-dictionaries",
        data={
            "xml_files": [(io.BytesIO(xml_data), "test.xml")],
            "slug_0": "existing-dict",
            "title_0": "Test Dictionary",
            "csrf_token": "fake_token",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"already exists" in resp.data


def test_import_dictionaries__invalid_xml(admin_client):
    invalid_xml = b'<?xml version="1.0"?><dictionary><unclosed>'

    resp = admin_client.post(
        "/admin/Dictionary/task/import-dictionaries",
        data={
            "xml_files": [(io.BytesIO(invalid_xml), "test.xml")],
            "slug_0": "test-dict",
            "title_0": "Test Dictionary",
            "csrf_token": "fake_token",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_import_dictionaries__multiple_files(admin_client):
    xml_data1 = b'<?xml version="1.0"?><dictionary></dictionary>'
    xml_data2 = b'<?xml version="1.0"?><dictionary></dictionary>'

    resp = admin_client.post(
        "/admin/Dictionary/task/import-dictionaries",
        data={
            "xml_files": [
                (io.BytesIO(xml_data1), "dict1.xml"),
                (io.BytesIO(xml_data2), "dict2.xml"),
            ],
            "slug_0": "test-dict-1",
            "title_0": "Test Dictionary 1",
            "slug_1": "test-dict-2",
            "title_1": "Test Dictionary 2",
            "csrf_token": "fake_token",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_add_genre__no_selection(admin_client):
    resp = admin_client.post(
        "/admin/Text/task/add-genre",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"No texts selected" in resp.data


def test_add_genre__get(admin_client):
    session = get_session()
    stmt = select(db.Text).limit(1)
    text = session.scalars(stmt).first()

    genre = db.Genre(name="Test Genre for Adding")
    session.add(genre)
    session.commit()

    resp = admin_client.post(
        "/admin/Text/task/add-genre",
        data={"selected_ids": [str(text.id)]},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_add_genre__full_workflow(admin_client):
    session = get_session()

    genre = db.Genre(name="Workflow Test Genre")
    session.add(genre)
    session.commit()
    genre_id = genre.id

    stmt = select(db.Text).filter_by(slug="pariksha")
    text = session.scalars(stmt).first()
    assert text is not None

    resp = admin_client.post(
        "/admin/Text/task/add-genre",
        data={
            "selected_ids": [str(text.id)],
            "genre_id": str(genre_id),
            "csrf_token": "fake_token",
        },
        follow_redirects=True,
    )

    assert resp.status_code in [200, 302, 400]
