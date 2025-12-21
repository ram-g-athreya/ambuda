import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

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


@app.task(bind=True)
def create_text_export(self, text_id: int, export_type: str, app_environment: str):
    create_text_export_inner(text_id, export_type, app_environment)
