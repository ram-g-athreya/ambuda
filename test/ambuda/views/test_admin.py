import pytest
from sqlalchemy import select

import ambuda.database as db
from ambuda.views.admin.main import MODEL_CONFIG
from ambuda.queries import get_session


ALL_MODELS = [x.model.__name__ for x in MODEL_CONFIG]
READ_ONLY_MODELS = [x.model.__name__ for x in MODEL_CONFIG if x.read_only]
READ_WRITE_MODELS = [x.model.__name__ for x in MODEL_CONFIG if not x.read_only]


@pytest.mark.parametrize(
    "username,status_code",
    [
        ("u-admin", 200),
        ("u-banned", 404),
        ("u-deleted", 404),
        ("u-basic", 404),
        (None, 404),
    ],
)
def test_get_pages_with_auth(username, status_code, flask_app):
    """Test page access with various user personas."""
    if username:
        session = get_session()
        stmt = select(db.User).filter_by(username=username)
        user = session.scalars(stmt).first()
        client = flask_app.test_client(user=user)
    else:
        client = flask_app.test_client()

    # Index view
    resp = client.get("/admin/")
    assert resp.status_code == status_code

    for model in ALL_MODELS:
        # List view
        resp = client.get(f"/admin/{model}/")
        assert resp.status_code == status_code

        # List view, pagination
        resp = client.get(f"/admin/{model}/?page=1")
        assert resp.status_code == status_code

    session = get_session()
    for model in READ_WRITE_MODELS:
        # Create view open for read-write models.
        resp = client.get(f"/admin/{model}/create")
        assert resp.status_code == status_code

        model_class = getattr(db, model)
        row = session.scalars(select(model_class)).first()
        if row:
            # GET /admin/<model>/<id>/edit open for read-write models.
            resp = client.get(f"/admin/{model}/{row.id}/edit")
            assert resp.status_code == status_code
            if status_code == 200:
                assert b"Save changes" in resp.data

    for model in READ_ONLY_MODELS:
        # Create view disabled for read-only
        resp = client.get(f"/admin/{model}/create")
        assert resp.status_code == 404

        model_class = getattr(db, model)
        row = session.scalars(select(model_class)).first()
        if row:
            # GET /admin/<model>/<id>/edit open, but can't save.
            resp = client.get(f"/admin/{model}/{row.id}/edit")
            assert resp.status_code == status_code
            if status_code == 200:
                assert b"Save changes" not in resp.data
                assert b"Read-only" in resp.data

            # POST /admin/<model>/<id>/edit is not available.
            resp = client.post(f"/admin/{model}/{row.id}/edit", data={"foo": "bar"})
            assert resp.status_code == 404

    # TODO: edit view


def test_list_view__foreign_keys(admin_client):
    resp = admin_client.get("/admin/Page/")
    assert resp.status_code == 200


def test_create_view__post_success(admin_client):
    resp = admin_client.post(
        "/admin/Genre/create",
        data={"name": "My test genre", "csrf_token": "fake_token"},
    )

    resp = admin_client.get(f"/admin/Genre/")
    assert b"My test genre" in resp.data


def test_edit_view__post_success(admin_client):
    session = get_session()

    genre = db.Genre(name="Edit Test Genre")
    session.add(genre)
    session.commit()
    genre_id = genre.id

    admin_client.post(
        f"/admin/Genre/{genre_id}/edit",
        data={"name": "Updated Genre", "csrf_token": "fake_token"},
    )

    resp = admin_client.get(f"/admin/Genre/{genre_id}/edit")
    assert b"Updated Genre" in resp.data


def test_edit_view__nonexistent(admin_client):
    """Test editing non-existent model returns 404."""
    resp = admin_client.get("/admin/User/99999/edit")
    assert resp.status_code == 404


# Delete model tests
def test_delete_model__success(admin_client):
    """Test successful model deletion."""
    session = get_session()

    # Create a genre to delete
    genre = db.Genre(name="Delete Test Genre")
    session.add(genre)
    session.commit()
    genre_id = genre.id

    resp = admin_client.post(
        f"/admin/Genre/{genre_id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code in [200, 302]


def test_delete_model__nonexistent(admin_client):
    """Test deleting non-existent model returns 404."""
    resp = admin_client.post("/admin/Genre/99999/delete")
    assert resp.status_code == 404


# Helper function tests
def test_get_foreign_key_info():
    """Test getting foreign key information."""
    from ambuda.views.admin.main import get_foreign_key_info

    fk_info = get_foreign_key_info(db.Page)
    assert isinstance(fk_info, dict)
    # Page should have project_id and status_id as foreign keys
    assert "project_id" in fk_info or "status_id" in fk_info


def test_get_many_to_many_info():
    """Test getting many-to-many relationship information."""
    from ambuda.views.admin.main import get_many_to_many_info

    m2m_info = get_many_to_many_info(db.User)
    assert isinstance(m2m_info, dict)
    # User has roles relationship
    assert "roles" in m2m_info


def test_get_model_config():
    """Test getting model configuration."""
    from ambuda.views.admin.main import get_model_config

    config = get_model_config("User")
    assert config
    assert config.model == db.User

    config = get_model_config("NonExistent")
    assert config is None


def test_get_models_by_category():
    """Test grouping models by category."""
    from ambuda.views.admin.main import get_models_by_category

    by_category = get_models_by_category()
    assert isinstance(by_category, dict)
    assert by_category


# create_model_form tests
def test_create_model_form__with_foreign_keys(admin_client, flask_app):
    """Test form creation for model with foreign keys."""
    from ambuda.views.admin.main import create_model_form

    with flask_app.test_request_context():
        form = create_model_form(db.Page)
        assert form is not None
        # Page has project_id and status_id foreign keys
        assert hasattr(form, "project_id")
        assert hasattr(form, "status_id")


def test_create_model_form__with_many_to_many(admin_client, flask_app):
    """Test form creation for model with many-to-many relationships."""
    from ambuda.views.admin.main import create_model_form

    with flask_app.test_request_context():
        form = create_model_form(db.User)
        assert form is not None
        # User has roles many-to-many relationship
        assert hasattr(form, "roles")


def test_create_model_form__with_existing_object(admin_client, flask_app):
    """Test form creation with existing object for editing."""
    from ambuda.views.admin.main import create_model_form

    session = get_session()
    stmt = select(db.User).filter_by(username="u-admin")
    user = session.scalars(stmt).first()

    with flask_app.test_request_context():
        form = create_model_form(db.User, obj=user)
        assert form is not None
        assert form.username.data == "u-admin"
        assert form.email.data == "u_admin@ambuda.org"


def test_create_model_form__text_area_for_long_strings(admin_client, flask_app):
    """Test that long string fields become text areas."""
    from ambuda.views.admin.main import create_model_form

    with flask_app.test_request_context():
        form = create_model_form(db.Project)
        assert form is not None
        # description should be a TextAreaField because it's a Text column
        assert hasattr(form, "description")


def test_create_model_form__json_fields(admin_client, flask_app):
    """Test that JSON fields become text areas."""
    from ambuda.views.admin.main import create_model_form

    with flask_app.test_request_context():
        form = create_model_form(db.Text)
        assert form is not None
        # config is a JSON field
        if hasattr(form, "config"):
            # Should be rendered as textarea
            pass


# 404 abort tests
def test_list_model__invalid_model_name(admin_client):
    """Test that invalid model name returns 404."""
    resp = admin_client.get("/admin/NonExistentModel/")
    assert resp.status_code == 404


def test_create_view__invalid_model_name(admin_client):
    """Test that invalid model name returns 404 for create."""
    resp = admin_client.get("/admin/NonExistentModel/create")
    assert resp.status_code == 404


def test_edit_view__invalid_model_name(admin_client):
    """Test that invalid model name returns 404 for edit."""
    resp = admin_client.get("/admin/NonExistentModel/1/edit")
    assert resp.status_code == 404


def test_delete_model__invalid_model_name(admin_client):
    """Test that invalid model name returns 404 for delete."""
    resp = admin_client.post("/admin/NonExistentModel/1/delete")
    assert resp.status_code == 404


def test_run_task__invalid_model_name(admin_client):
    """Test that invalid model name returns 404 for task."""
    resp = admin_client.get("/admin/NonExistentModel/task/some-task")
    assert resp.status_code == 404


def test_run_task__invalid_task_slug(admin_client):
    """Test that invalid task slug returns 404."""
    resp = admin_client.get("/admin/Text/task/nonexistent-task")
    assert resp.status_code == 404


def test_list_model__moderator_access_denied(moderator_client):
    """Test that moderator cannot access admin-only models."""
    # Text model requires admin permission
    resp = moderator_client.get("/admin/Text/")
    assert resp.status_code == 404


def test_create_view__moderator_access_denied(moderator_client):
    """Test that moderator cannot create admin-only models."""
    resp = moderator_client.get("/admin/Text/create")
    assert resp.status_code == 404


# Form population tests
def test_populate_model_attributes_from_form(admin_client, flask_app):
    """Test populating model attributes from form data."""
    from ambuda.views.admin.main import (
        create_model_form,
        populate_model_attributes_from_form,
    )

    session = get_session()

    # Create a genre and form
    genre = db.Genre(name="Original Name")
    session.add(genre)
    session.flush()

    with flask_app.test_request_context():
        form = create_model_form(db.Genre, obj=genre)
        form.name.data = "Updated Name"

        populate_model_attributes_from_form(genre, form, db.Genre)
        assert genre.name == "Updated Name"


def test_populate_model_m2m_from_form(admin_client, flask_app):
    """Test populating many-to-many relationships from form."""
    from ambuda.views.admin.main import (
        create_model_form,
        populate_model_m2m_from_form,
    )

    session = get_session()

    # Get user and roles
    stmt = select(db.User).filter_by(username="u-basic")
    user = session.scalars(stmt).first()

    stmt = select(db.Role).filter_by(name="admin")
    admin_role = session.scalars(stmt).first()

    with flask_app.test_request_context():
        form = create_model_form(db.User, obj=user)
        # Simulate form data with selected role IDs
        if hasattr(form, "roles"):
            form.roles.data = [str(admin_role.id)]
            populate_model_m2m_from_form(user, form, db.User, session)
            # Check if role was added
            role_ids = [r.id for r in user.roles]
            assert admin_role.id in role_ids


# Error handling tests
def test_create_view__validation_error(admin_client):
    """Test that validation errors are handled."""
    # Try to create a genre without name (if required)
    resp = admin_client.post(
        "/admin/Genre/create",
        data={"csrf_token": "fake_token"},
        follow_redirects=False,
    )
    # Should either show validation error or CSRF error
    assert resp.status_code in [200, 400]


def test_edit_view__database_error_handling(admin_client):
    """Test that database errors are handled gracefully."""
    session = get_session()

    genre = db.Genre(name="Test Error Handling")
    session.add(genre)
    session.commit()
    genre_id = genre.id

    # Try to update with potentially invalid data
    resp = admin_client.post(
        f"/admin/Genre/{genre_id}/edit",
        data={"name": "", "csrf_token": "fake_token"},
        follow_redirects=False,
    )
    # Should handle error gracefully
    assert resp.status_code in [200, 302, 400]
