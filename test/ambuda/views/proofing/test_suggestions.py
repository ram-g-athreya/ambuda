"""Tests for the suggestions flow."""

from sqlalchemy import select

import ambuda.database as db
from ambuda.models.proofing import SuggestionStatus
from ambuda.queries import get_session


VALID_CONTENT = "<page>\n<p>suggested content</p>\n</page>"


def _create_suggestion(session, project_id, page_id, revision_id, user_id=None):
    """Helper to create a suggestion directly in the DB."""
    suggestion = db.Suggestion(
        project_id=project_id,
        page_id=page_id,
        revision_id=revision_id,
        user_id=user_id,
        content=VALID_CONTENT,
        explanation="fixed a typo",
    )
    session.add(suggestion)
    session.commit()
    return suggestion


def _get_test_ids(session):
    """Get project_id, page_id, revision_id for test-project/page 1."""
    project = session.scalars(select(db.Project).filter_by(slug="test-project")).one()
    page = session.scalars(
        select(db.Page).filter(
            (db.Page.project_id == project.id) & (db.Page.slug == "1")
        )
    ).one()
    revision = page.revisions[-1]
    return project.id, page.id, revision.id


def test_suggestions_index__unauth(client):
    r = client.get("/proofing/suggestions/")
    assert r.status_code == 302


def test_suggestions_index__no_p1(no_p1_client):
    r = no_p1_client.get("/proofing/suggestions/")
    assert r.status_code == 302


def test_suggestions_index__p1(rama_client):
    r = rama_client.get("/proofing/suggestions/")
    assert r.status_code == 200
    assert "Suggestions" in r.text


def test_suggestions_index__filter_by_status(rama_client):
    r = rama_client.get("/proofing/suggestions/?status=accepted")
    assert r.status_code == 200

    r = rama_client.get("/proofing/suggestions/?status=rejected")
    assert r.status_code == 200

    # Invalid status falls back to pending
    r = rama_client.get("/proofing/suggestions/?status=foo")
    assert r.status_code == 200


def test_suggestions_index__cursor_pagination(rama_client, flask_app):
    with flask_app.app_context():
        session = get_session()
        project_id, page_id, revision_id = _get_test_ids(session)
        s1 = _create_suggestion(session, project_id, page_id, revision_id)
        s2 = _create_suggestion(session, project_id, page_id, revision_id)
        s1_id, s2_id = s1.id, s2.id

    r = rama_client.get(f"/proofing/suggestions/?before={s2_id}")
    assert r.status_code == 200
    assert f"/suggestions/{s2_id}/accept" not in r.text
    assert f"/suggestions/{s1_id}/accept" in r.text

    # Invalid cursor is ignored gracefully
    r = rama_client.get("/proofing/suggestions/?before=notanumber")
    assert r.status_code == 200


def test_edit_post__no_p1_creates_suggestion(no_p1_client, flask_app):
    with flask_app.app_context():
        session = get_session()
        before_count = len(session.scalars(select(db.Suggestion)).all())

    r = no_p1_client.post(
        "/proofing/test-project/1/",
        data={
            "content": VALID_CONTENT,
            "version": "0",
            "status": "reviewed-0",
            "summary": "",
            "explanation": "my explanation",
        },
    )
    assert r.status_code == 200
    assert "Your suggestion has been submitted for review" in r.text

    with flask_app.app_context():
        session = get_session()
        after = session.scalars(select(db.Suggestion)).all()
        assert len(after) == before_count + 1
        newest = after[-1]
        assert newest.explanation == "my explanation"
        assert newest.status == SuggestionStatus.PENDING
        assert newest.user_id is not None


def test_edit_post__anonymous_creates_suggestion(client, flask_app):
    r = client.post(
        "/proofing/test-project/1/",
        data={
            "content": VALID_CONTENT,
            "version": "0",
            "status": "reviewed-0",
            "summary": "",
            "explanation": "",
        },
    )
    assert r.status_code == 200
    assert "Your suggestion has been submitted for review" in r.text

    with flask_app.app_context():
        session = get_session()
        stmt = select(db.Suggestion).order_by(db.Suggestion.id.desc())
        newest = session.scalars(stmt).first()
        assert newest.user_id is None


def test_edit_post__p1_saves_directly(rama_client):
    r = rama_client.post(
        "/proofing/test-project/1/",
        data={
            "content": VALID_CONTENT,
            "version": "0",
            "status": "reviewed-0",
            "summary": "",
        },
    )
    assert r.status_code == 200
    assert "suggestion" not in r.text.lower()
    assert "Saved changes" in r.text


def test_accept__success(rama_client, flask_app):
    with flask_app.app_context():
        session = get_session()
        project_id, page_id, revision_id = _get_test_ids(session)
        suggestion = _create_suggestion(session, project_id, page_id, revision_id)
        suggestion_id = suggestion.id

    r = rama_client.post(f"/proofing/suggestions/{suggestion_id}/accept")
    assert r.status_code == 302

    with flask_app.app_context():
        session = get_session()
        s = session.get(db.Suggestion, suggestion_id)
        assert s.status == SuggestionStatus.ACCEPTED


def test_accept__stale_revision(rama_client, flask_app):
    with flask_app.app_context():
        session = get_session()
        project_id, page_id, revision_id = _get_test_ids(session)
        suggestion = _create_suggestion(session, project_id, page_id, revision_id=99999)
        suggestion_id = suggestion.id

    r = rama_client.post(f"/proofing/suggestions/{suggestion_id}/accept")
    assert r.status_code == 302

    with flask_app.app_context():
        session = get_session()
        s = session.get(db.Suggestion, suggestion_id)
        assert s.status == SuggestionStatus.PENDING


def test_reject__success(rama_client, flask_app):
    with flask_app.app_context():
        session = get_session()
        project_id, page_id, revision_id = _get_test_ids(session)
        suggestion = _create_suggestion(session, project_id, page_id, revision_id)
        suggestion_id = suggestion.id

    r = rama_client.post(f"/proofing/suggestions/{suggestion_id}/reject")
    assert r.status_code == 302

    with flask_app.app_context():
        session = get_session()
        s = session.get(db.Suggestion, suggestion_id)
        assert s.status == SuggestionStatus.REJECTED


def test_accept__nonexistent(rama_client):
    r = rama_client.post("/proofing/suggestions/99999/accept")
    assert r.status_code == 302


def test_reject__nonexistent(rama_client):
    r = rama_client.post("/proofing/suggestions/99999/reject")
    assert r.status_code == 302


def test_accept__unauth(client, flask_app):
    with flask_app.app_context():
        session = get_session()
        project_id, page_id, revision_id = _get_test_ids(session)
        suggestion = _create_suggestion(session, project_id, page_id, revision_id)
        suggestion_id = suggestion.id

    r = client.post(f"/proofing/suggestions/{suggestion_id}/accept")
    assert r.status_code == 302

    with flask_app.app_context():
        session = get_session()
        s = session.get(db.Suggestion, suggestion_id)
        assert s.status == SuggestionStatus.PENDING


def test_reject__no_p1(no_p1_client, flask_app):
    with flask_app.app_context():
        session = get_session()
        project_id, page_id, revision_id = _get_test_ids(session)
        suggestion = _create_suggestion(session, project_id, page_id, revision_id)
        suggestion_id = suggestion.id

    r = no_p1_client.post(f"/proofing/suggestions/{suggestion_id}/reject")
    assert r.status_code == 302

    with flask_app.app_context():
        session = get_session()
        s = session.get(db.Suggestion, suggestion_id)
        assert s.status == SuggestionStatus.PENDING


def test_edit_page__p1_sees_save_button(rama_client):
    r = rama_client.get("/proofing/test-project/1/")
    assert "Save" in r.text


def test_edit_page__no_p1_sees_suggest_button(no_p1_client):
    r = no_p1_client.get("/proofing/test-project/1/")
    assert "Suggest" in r.text


def test_edit_page__anonymous_sees_suggest_button(client):
    r = client.get("/proofing/test-project/1/")
    assert "Suggest" in r.text
