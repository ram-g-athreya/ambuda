import json
import tempfile
from datetime import datetime
from pathlib import Path

from flask import (
    request,
    redirect,
    url_for,
    flash,
    render_template,
    jsonify,
    make_response,
)
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, MultipleFileField
from sqlalchemy import inspect, select
from sqlalchemy.types import DateTime
from wtforms import SelectField
from wtforms.validators import DataRequired

import ambuda.database as db
import ambuda.queries as q
import ambuda.data_utils as data_utils
from ambuda.utils.tei_parser import parse_document


def get_model_configs_context():
    """Get model configs for template context."""
    from .main import MODEL_CONFIG, get_models_by_category

    return {
        "model_configs": {c.model.__name__: c for c in MODEL_CONFIG},
        "models_by_category": get_models_by_category(),
    }


def import_text(model_name):
    """Import texts from XML files."""

    class UploadTextForm(FlaskForm):
        xml_files = MultipleFileField("XML Files", validators=[FileRequired()])

    form = UploadTextForm()

    if form.validate_on_submit():
        xml_files = form.xml_files.data
        session = q.get_session()

        success_count = 0
        error_count = 0
        errors = []

        for index, xml_file in enumerate(xml_files):
            filename = xml_file.filename
            if not filename.endswith(".xml"):
                errors.append(f"{filename}: Must be an XML file")
                error_count += 1
                continue

            # Get slug and title from form data
            slug = request.form.get(f"slug_{index}", "").strip()
            title = request.form.get(f"title_{index}", "").strip()

            if not slug:
                errors.append(f"{filename}: Slug is required")
                error_count += 1
                continue
            if not title:
                errors.append(f"{filename}: Title is required")
                error_count += 1
                continue

            stmt = select(db.Text).filter_by(slug=slug)
            if session.scalars(stmt).first():
                errors.append(f"{filename}: A text with slug '{slug}' already exists")
                error_count += 1
                continue

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", suffix=".xml", delete=False
                ) as tmp_file:
                    xml_file.save(tmp_file)
                    tmp_path = Path(tmp_file.name)

                document = parse_document(tmp_path)
                data_utils.create_text_from_document(session, slug, title, document)
                success_count += 1

            except Exception as e:
                session.rollback()
                errors.append(f"{filename}: {str(e)}")
                error_count += 1
            finally:
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()

        if success_count > 0:
            flash(f"Successfully uploaded {success_count} text(s)", "success")
        if error_count > 0:
            flash(
                f"{error_count} error(s): {'; '.join(errors[:5])}{'...' if len(errors) > 5 else ''}",
                "error",
            )

        if success_count > 0 or error_count > 0:
            return redirect(url_for("admin.list_model", model_name=model_name))

    return render_template(
        "admin/task-import-text.html",
        model_name=model_name,
        form=form,
        **get_model_configs_context(),
    )


def import_parse_data(model_name):
    """Import parse data for texts from TXT files."""

    class UploadParseDataForm(FlaskForm):
        parse_files = MultipleFileField("Parse Data Files", validators=[FileRequired()])

    form = UploadParseDataForm()

    if form.validate_on_submit():
        parse_files = form.parse_files.data
        session = q.get_session()

        success_count = 0
        error_count = 0
        errors = []

        for parse_file in parse_files:
            # Derive text slug from filename (e.g., "bhagavad-gita.txt" -> "bhagavad-gita")
            filename = parse_file.filename
            if not filename.endswith(".txt"):
                errors.append(f"{filename}: Must be a .txt file")
                error_count += 1
                continue

            text_slug = filename[:-4]  # Remove .txt extension

            stmt = select(db.Text).filter_by(slug=text_slug)
            text = session.scalars(stmt).first()
            if not text:
                errors.append(f"{filename}: Text with slug '{text_slug}' not found")
                error_count += 1
                continue

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", suffix=".txt", delete=False
                ) as tmp_file:
                    parse_file.save(tmp_file)
                    tmp_path = Path(tmp_file.name)

                data_utils.add_parse_data(session, text_slug, tmp_path)
                success_count += 1

            except Exception as e:
                session.rollback()
                errors.append(f"{filename}: {str(e)}")
                error_count += 1
            finally:
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()

        if success_count > 0:
            flash(
                f"Successfully uploaded parse data for {success_count} text(s)",
                "success",
            )
        if error_count > 0:
            flash(
                f"{error_count} error(s): {'; '.join(errors[:5])}{'...' if len(errors) > 5 else ''}",
                "error",
            )

        if success_count > 0 or error_count > 0:
            return redirect(url_for("admin.list_model", model_name=model_name))

    return render_template(
        "admin/task-import-parse-data.html",
        model_name=model_name,
        form=form,
        **get_model_configs_context(),
    )


def add_genre_to_texts(model_name):
    """Batch action to add a genre to multiple texts."""

    class AddGenreForm(FlaskForm):
        genre_id = SelectField("Genre", coerce=int, validators=[DataRequired()])

    session = q.get_session()
    genres = session.query(db.Genre).order_by(db.Genre.name).all()

    form = AddGenreForm()
    form.genre_id.choices = [(g.id, g.name) for g in genres]
    selected_ids = request.form.getlist("selected_ids")

    if not selected_ids:
        flash("No texts selected", "error")
        return redirect(url_for("admin.list_model", model_name=model_name))

    if form.validate_on_submit():
        genre_id = form.genre_id.data

        try:
            updated_count = 0
            for text_id in selected_ids:
                text = session.get(db.Text, int(text_id))
                if text:
                    text.genre_id = genre_id
                    updated_count += 1

            session.commit()
            genre_name = session.get(db.Genre, genre_id).name
            flash(
                f"Successfully added genre '{genre_name}' to {updated_count} text(s)",
                "success",
            )
            return redirect(url_for("admin.list_model", model_name=model_name))

        except Exception as e:
            session.rollback()
            flash(f"Error adding genre: {str(e)}", "error")

    texts = []
    for text_id in selected_ids:
        text = session.get(db.Text, int(text_id))
        if text:
            texts.append(text)

    return render_template(
        "admin/task-add-genre.html",
        model_name=model_name,
        form=form,
        texts=texts,
        selected_ids=selected_ids,
        **get_model_configs_context(),
    )


def import_metadata(model_name):
    """Import text metadata from a JSON file."""

    class UploadMetadataForm(FlaskForm):
        json_file = FileField("JSON File", validators=[FileRequired()])

    form = UploadMetadataForm()

    if form.validate_on_submit():
        json_file = form.json_file.data

        session = q.get_session()
        try:
            metadata_list = json.load(json_file.stream)

            updated_count, not_found_slugs = data_utils.import_text_metadata(
                session, metadata_list
            )

            if not_found_slugs:
                flash(
                    (
                        f"Updated {updated_count} text(s). "
                        f"Warning: {len(not_found_slugs)} slug(s) not found: "
                        f"{', '.join(not_found_slugs[:5])}{'...' if len(not_found_slugs) > 5 else ''}"
                    ),
                    "warning",
                )
            else:
                flash(f"Successfully updated {updated_count} text(s)", "success")

            return redirect(url_for("admin.list_model", model_name=model_name))

        except Exception as e:
            session.rollback()
            flash(f"Error importing metadata: {str(e)}", "error")

    return render_template(
        "admin/task-import-metadata.html",
        model_name=model_name,
        form=form,
        **get_model_configs_context(),
    )


def export_metadata(model_name):
    """Export Text metadata as JSON."""
    session = q.get_session()

    texts = session.query(db.Text).all()
    export_data = []
    for text in texts:
        text_dict = {
            "slug": text.slug,
            "title": text.title,
            "header": text.header,
            "config": json.loads(text.config) if text.config else None,
            "genre": text.genre.name if text.genre else None,
        }
        export_data.append(text_dict)

    response = make_response(jsonify(export_data))
    response.headers["Content-Disposition"] = "attachment; filename=texts_metadata.json"
    response.headers["Content-Type"] = "application/json"

    return response


def import_dictionaries(model_name):
    """Import dictionaries from XML files."""

    class UploadDictionaryForm(FlaskForm):
        xml_files = MultipleFileField("XML Files", validators=[FileRequired()])

    form = UploadDictionaryForm()

    if form.validate_on_submit():
        xml_files = form.xml_files.data
        session = q.get_session()

        success_count = 0
        error_count = 0
        errors = []
        total_entries = 0

        for index, xml_file in enumerate(xml_files):
            filename = xml_file.filename
            if not filename.endswith(".xml"):
                errors.append(f"{filename}: Must be an XML file")
                error_count += 1
                continue

            slug = request.form.get(f"slug_{index}", "").strip()
            title = request.form.get(f"title_{index}", "").strip()

            if not slug:
                errors.append(f"{filename}: Slug is required")
                error_count += 1
                continue
            if not title:
                errors.append(f"{filename}: Title is required")
                error_count += 1
                continue

            session = q.get_session()
            stmt = select(db.Dictionary).filter_by(slug=slug)
            dictionary = session.scalars(stmt).first()
            if dictionary:
                errors.append(
                    f"{filename}: A dictionary with slug '{slug}' already exists"
                )
                error_count += 1
                continue

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", suffix=".xml", delete=False
                ) as tmp_file:
                    xml_file.save(tmp_file)
                    tmp_path = Path(tmp_file.name)

                entry_count = data_utils.import_dictionary_from_xml(
                    slug=slug, title=title, path=tmp_path
                )
                total_entries += entry_count
                success_count += 1

            except Exception as e:
                session.rollback()
                errors.append(f"{filename}: {str(e)}")
                error_count += 1
            finally:
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()

        # Display summary
        if success_count > 0:
            flash(
                (
                    f"Successfully imported {success_count} dictionar{'ies' if success_count > 1 else 'y'} "
                    f"({total_entries} entries)"
                ),
                "success",
            )
        if error_count > 0:
            flash(
                f"{error_count} error(s): {'; '.join(errors[:5])}{'...' if len(errors) > 5 else ''}",
                "error",
            )

        if success_count > 0 or error_count > 0:
            return redirect(url_for("admin.list_model", model_name=model_name))

    return render_template(
        "admin/task-import-dictionary.html",
        model_name=model_name,
        form=form,
        **get_model_configs_context(),
    )
