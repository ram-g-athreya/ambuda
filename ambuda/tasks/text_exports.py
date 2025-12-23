import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from celery import chain, group
from sqlalchemy import select

from ambuda import database as db
from ambuda import queries as q
from ambuda.s3_utils import S3Path
from ambuda.tasks import app
from ambuda.utils import text_exports
from config import create_config_only_app
from pydantic import BaseModel


EXPORTS = {x.type: x for x in text_exports.EXPORTS}


def create_text_export_inner(
    text_id: int, export_type: str, app_environment: str
) -> None:
    app = create_config_only_app(app_environment)
    with app.app_context():
        session = q.get_session()
        text = session.get(db.Text, text_id)
        if not text:
            raise ValueError(f"Text with id {text_id} not found")

        logging.info(f"Creating {export_type} export for {text.slug}")

        export_config = EXPORTS.get(export_type)
        if not export_config:
            raise ValueError(f"Unknown export type: {export_type}")

        with tempfile.NamedTemporaryFile(mode="wb") as tmp_file:
            tmp_path = Path(tmp_file.name)

            try:
                export_config.write_to_local_file(text, tmp_path)
                file_size: int = tmp_path.stat().st_size
                export_slug = export_config.slug(text)
                logging.info(f"Wrote export to local path {tmp_path}")

                bucket = app.config["S3_BUCKET"]
                key = f"text-exports/{export_slug}"
                s3_path = S3Path(bucket, key)
                s3_path.upload_file(tmp_path)
                logging.info(f"Uploaded {export_type} export to {s3_path}")

                stmt = select(db.TextExport).filter_by(slug=export_slug)
                text_export = session.scalars(stmt).first()

                if text_export:
                    text_export.s3_path = s3_path.path
                    text_export.size = file_size
                    text_export.updated_at = datetime.now(UTC)
                    logging.info(f"Updated existing TextExport: {export_slug}")
                else:
                    text_export = db.TextExport(
                        text_id=text_id,
                        slug=export_slug,
                        export_type=export_type,
                        s3_path=s3_path.path,
                        size=file_size,
                    )
                    session.add(text_export)
                    logging.info(f"Created new TextExport: {export_slug}")
                session.commit()
            except Exception as e:
                logging.warning(f"Exception while creating export: {e}")
                raise e


def create_text_export_with_xml_download(
    text_id: int, export_type: str, app_environment: str
) -> None:
    app = create_config_only_app(app_environment)
    with app.app_context():
        session = q.get_session()
        text = session.get(db.Text, text_id)
        if not text:
            raise ValueError(f"Text with id {text_id} not found")

        logging.info(f"Creating {export_type} export for {text.slug} (requires XML)")

        export_config = EXPORTS.get(export_type)
        if not export_config:
            raise ValueError(f"Unknown export type: {export_type}")

        xml_slug = f"{text.slug}.xml"
        stmt = select(db.TextExport).filter_by(slug=xml_slug)
        xml_export = session.scalars(stmt).first()

        if not xml_export:
            raise FileNotFoundError(
                f"XML export not found for {text.slug}. "
                "XML must be created before this export type."
            )

        if not xml_export.s3_path:
            raise ValueError(
                f"XML export for {text.slug} exists but has no S3 path. "
                "XML creation may have failed or is incomplete."
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)

            xml_temp_path = temp_dir_path / f"{text.slug}.xml"
            xml_s3_path = S3Path.from_path(xml_export.s3_path)
            xml_s3_path.download_file(xml_temp_path)
            logging.info(f"Downloaded XML from {xml_s3_path} to {xml_temp_path}")

            output_temp_path = temp_dir_path / export_config.slug(text)
            export_config.write_to_local_file(text, output_temp_path)
            file_size = output_temp_path.stat().st_size
            export_slug = export_config.slug(text)
            logging.info(f"Created {export_type} export at {output_temp_path}")

            bucket = app.config["S3_BUCKET"]
            key = f"text-exports/{export_slug}"
            s3_path = S3Path(bucket, key)
            s3_path.upload_file(output_temp_path)
            logging.info(f"Uploaded {export_type} export to {s3_path}")

            stmt = select(db.TextExport).filter_by(slug=export_slug)
            text_export = session.scalars(stmt).first()

            if text_export:
                text_export.s3_path = s3_path.path
                text_export.size = file_size
                text_export.updated_at = datetime.now(UTC)
                logging.info(f"Updated existing TextExport: {export_slug}")
            else:
                text_export = db.TextExport(
                    text_id=text_id,
                    slug=export_slug,
                    export_type=export_type,
                    s3_path=s3_path.path,
                    size=file_size,
                )
                session.add(text_export)
                logging.info(f"Created new TextExport: {export_slug}")
            session.commit()


@app.task(bind=True)
def create_text_export(self, text_id: int, export_type: str, app_environment: str):
    create_text_export_inner(text_id, export_type, app_environment)


@app.task(bind=True)
def delete_text_export(self, export_id: int, app_environment: str):
    app = create_config_only_app(app_environment)
    with app.app_context():
        session = q.get_session()
        text_export = session.get(db.TextExport, export_id)
        if not text_export:
            logging.warning(f"TextExport with id {export_id} not found")
            return

        try:
            s3_path = S3Path.from_path(text_export.s3_path)
            try:
                s3_path.delete()
                logging.info(f"Deleted S3 file: {s3_path}")
            except Exception as e:
                logging.warning(f"Could not delete S3 file: {e}")

            session.delete(text_export)
            session.commit()
            logging.info(f"Deleted TextExport record: {export_id}")

        except Exception as e:
            session.rollback()
            logging.error(f"Error deleting TextExport {export_id}: {e}")
            raise


# Specialized tasks for Celery chains


@app.task(bind=True)
def create_xml_export(self, text_id: int, app_environment: str):
    create_text_export_inner(text_id, text_exports.ExportType.XML, app_environment)


@app.task(bind=True)
def create_txt_export(self, text_id: int, app_environment: str):
    create_text_export_with_xml_download(
        text_id, text_exports.ExportType.PLAIN_TEXT, app_environment
    )


@app.task(bind=True)
def create_pdf_export(self, text_id: int, app_environment: str):
    create_text_export_with_xml_download(
        text_id, text_exports.ExportType.PDF, app_environment
    )


@app.task(bind=True)
def create_tokens_export(self, text_id: int, app_environment: str):
    create_text_export_inner(text_id, text_exports.ExportType.TOKENS, app_environment)


def create_all_exports_for_text(text_id: int, app_environment: str):
    return chain(
        create_xml_export.si(text_id, app_environment),
        group(
            create_txt_export.si(text_id, app_environment),
            create_pdf_export.si(text_id, app_environment),
            create_tokens_export.si(text_id, app_environment),
        ),
    )
