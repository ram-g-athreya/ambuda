"""Background tasks for proofing projects."""

import logging
import uuid
import os
import urllib.request
import urllib.parse
import json
import re
from pathlib import Path

# NOTE: `fitz` is the internal package name for PyMuPDF. PyPI hosts another
# package called `fitz` (https://pypi.org/project/fitz/) that is completely
# unrelated to PDF parsing.
import fitz
from slugify import slugify
from sqlalchemy import select

from ambuda import database as db
from ambuda.s3_utils import S3Path
from ambuda.tasks import app
from ambuda.tasks.utils import CeleryTaskStatus, TaskStatus, get_db_session


def _split_pdf_into_pages(
    pdf_path: Path, output_dir: Path, task_status: TaskStatus
) -> int:
    """Split the given PDF into N .jpg images, one image per page.

    :param pdf_path: filesystem path to the PDF we should process.
    :param output_dir: the directory to which we'll write these images.
    :return: the page count, which we use downstream.
    """
    doc = fitz.open(pdf_path)
    task_status.progress(0, doc.page_count)
    for page in doc:
        n = page.number + 1
        pix = page.get_pixmap(dpi=200)
        output_path = output_dir / f"{n}.jpg"
        pix.pil_save(output_path, optimize=True)
        task_status.progress(n, doc.page_count)
    return doc.page_count


def _add_project_to_database(
    session, display_title: str, slug: str, num_pages: int, creator_id: int
):
    """Create a project on the database.

    :param session: database session
    :param display_title: the project title
    :param slug: the project slug
    :param num_pages: the number of pages in the project
    :param creator_id: the user ID of the creator
    """

    logging.info(f"Creating project (slug = {slug}) ...")
    board = db.Board(title=f"{slug} discussion board")
    session.add(board)
    session.flush()

    project = db.Project(slug=slug, display_title=display_title, creator_id=creator_id)
    project.board_id = board.id
    session.add(project)
    session.flush()

    logging.info(f"Fetching project and status (slug = {slug}) ...")
    stmt = select(db.PageStatus).filter_by(name="reviewed-0")
    unreviewed = session.scalars(stmt).one()

    logging.info(f"Creating {num_pages} Page entries (slug = {slug}) ...")
    for n in range(1, num_pages + 1):
        session.add(
            db.Page(
                project_id=project.id,
                slug=str(n),
                order=n,
                status_id=unreviewed.id,
            )
        )
    session.commit()


def create_project_inner(
    *,
    display_title: str,
    pdf_path: str = None,
    pdf_url: str = None,
    output_dir: str = None,
    upload_folder: str = None,
    app_environment: str,
    creator_id: int,
    task_status: TaskStatus,
    engine=None,
):
    """Split the given PDF into pages and register the project on the database.

    We separate this function from `create_project` so that we can run this
    function in a non-Celery context (for example, in `cli.py`).

    :param display_title: the project's title.
    :param pdf_path: local path to the source PDF (for local uploads).
    :param pdf_url: URL to download PDF from (for URL uploads).
    :param output_dir: local path where page images will be stored.
    :param upload_folder: base upload folder (required for URL uploads).
    :param app_environment: the app environment, e.g. `"development"`.
    :param creator_id: the user that created this project.
    :param task_status: tracks progress on the task.
    :param engine: optional SQLAlchemy engine. Tests should pass this to share
                   the same :memory: database.
    """
    logging.info(f'Received upload task "{display_title}".')

    # Tasks must be idempotent. Exit if the project already exists.
    with get_db_session(app_environment, engine=engine) as (session, query, config_obj):
        slug = slugify(display_title)
        stmt = select(db.Project).filter_by(slug=slug)
        project = session.scalars(stmt).first()

        if project:
            raise ValueError(
                f'Project "{display_title}" already exists. Please choose a different title.'
            )

        # Handle URL-based uploads
        if pdf_url:
            if not upload_folder:
                raise ValueError("upload_folder is required for URL-based uploads.")

            # Create all directories for this project
            project_dir = Path(upload_folder) / "projects" / slug
            pdf_dir = project_dir / "pdf"
            pages_dir = project_dir / "pages"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pages_dir.mkdir(parents=True, exist_ok=True)

            # Download the PDF from the URL
            pdf_path = pdf_dir / "source.pdf"
            logging.info(f"Downloading PDF from {pdf_url}...")
            try:
                urllib.request.urlretrieve(pdf_url, pdf_path)
            except Exception as e:
                raise ValueError(f"Failed to download PDF from URL: {e}")

            # Validate that the downloaded file is a PDF
            if not pdf_path.suffix == ".pdf":
                pdf_path.unlink()  # Remove the downloaded file
                raise ValueError("The URL does not point to a valid PDF file.")
        else:
            # Local file upload path
            if not pdf_path or not output_dir:
                raise ValueError(
                    "pdf_path and output_dir are required for local uploads."
                )

            pdf_path = Path(pdf_path)
            pages_dir = Path(output_dir)

        num_pages = _split_pdf_into_pages(Path(pdf_path), Path(pages_dir), task_status)

        _add_project_to_database(
            session=session,
            display_title=display_title,
            slug=slug,
            num_pages=num_pages,
            creator_id=creator_id,
        )

        move_project_pdf_to_s3_inner(
            session=session,
            config_obj=config_obj,
            project_slug=slug,
            pdf_path=str(pdf_path),
        )

    task_status.success(num_pages, slug)


@app.task(bind=True)
def create_project(
    self,
    *,
    display_title: str,
    pdf_path: str = None,
    pdf_url: str = None,
    output_dir: str = None,
    upload_folder: str = None,
    app_environment: str,
    creator_id: int,
):
    """Split the given PDF into pages and register the project on the database.

    For argument details, see `create_project_inner`.
    """
    task_status = CeleryTaskStatus(self)
    create_project_inner(
        display_title=display_title,
        pdf_path=pdf_path,
        pdf_url=pdf_url,
        output_dir=output_dir,
        upload_folder=upload_folder,
        app_environment=app_environment,
        creator_id=creator_id,
        task_status=task_status,
    )


def move_project_pdf_to_s3_inner(*, session, config_obj, project_slug, pdf_path):
    """Temporary task to move project PDFs to S3.

    :param session: database session
    :param config_obj: config object
    :param project_slug: the project slug
    :param pdf_path: path to the PDF file
    """

    stmt = select(db.Project).filter_by(slug=project_slug)
    project = session.scalars(stmt).first()

    s3_bucket = config_obj.S3_BUCKET
    if not s3_bucket:
        logging.info(f"No s3 bucket found")
        return

    s3_dest = S3Path(bucket=s3_bucket, key=f"proofing/{project.uuid}/pdf/source.pdf")
    if s3_dest.exists():
        logging.info(f"S3 path {s3_dest} already exists.")
        return

    s3_dest.upload_file(pdf_path)
    logging.info(f"Uploaded {project.id} PDF path to {s3_dest}.")

    Path(pdf_path).unlink()
    logging.info(f"Removed local file {pdf_path}.")


@app.task(bind=True)
def move_project_pdf_to_s3(self, *, project_slug, pdf_path, app_environment):
    """Temporary task to move project PDFs to S3."""
    with get_db_session(app_environment) as (session, query, config_obj):
        move_project_pdf_to_s3_inner(
            session=session,
            config_obj=config_obj,
            project_slug=project_slug,
            pdf_path=pdf_path,
        )


def _extract_gdrive_folder_id(folder_url: str) -> str:
    """Extract the folder ID from a Google Drive folder URL.

    Supports formats like:
    - https://drive.google.com/drive/folders/FOLDER_ID
    - https://drive.google.com/drive/folders/FOLDER_ID?usp=sharing
    """
    # Try to extract folder ID using regex
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", folder_url)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract folder ID from URL: {folder_url}")


def _list_gdrive_folder_pdfs(folder_id: str, api_key: str = None):
    """List all PDF files in a public Google Drive folder.

    :param folder_id: The Google Drive folder ID
    :param api_key: Optional Google Drive API key
    :return: List of dicts with 'id' and 'name' keys
    """
    if api_key:
        # Use Google Drive API v3
        query = urllib.parse.quote(
            f"'{folder_id}' in parents and mimeType='application/pdf'"
        )
        url = f"https://www.googleapis.com/drive/v3/files?q={query}&key={api_key}&fields=files(id,name)"

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read())
                return data.get("files", [])
        except Exception as e:
            logging.error(f"Failed to list files using API: {e}")
            raise ValueError(
                f"Failed to access Google Drive folder. Make sure it's publicly accessible. Error: {e}"
            )
    else:
        raise ValueError(
            "Google Drive API key not configured. Please set GOOGLE_DRIVE_API_KEY in your configuration."
        )


def _get_gdrive_file_download_url(file_id: str) -> str:
    """Get the download URL for a Google Drive file.

    :param file_id: The Google Drive file ID
    :return: Direct download URL
    """
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def create_projects_from_gdrive_folder_inner(
    *,
    folder_url: str,
    upload_folder: str,
    app_environment: str,
    creator_id: int,
    task_status: TaskStatus,
    engine=None,
):
    """Create multiple projects from PDFs in a Google Drive folder.

    :param folder_url: Google Drive folder URL
    :param upload_folder: Base upload folder
    :param app_environment: The app environment
    :param creator_id: The user that created these projects
    :param task_status: Tracks progress on the task
    :param engine: Optional SQLAlchemy engine
    """
    logging.info(f"Processing Google Drive folder: {folder_url}")

    # Extract folder ID
    try:
        folder_id = _extract_gdrive_folder_id(folder_url)
        logging.info(f"Extracted folder ID: {folder_id}")
    except ValueError as e:
        raise ValueError(f"Invalid Google Drive folder URL: {e}")

    # Get API key from config
    with get_db_session(app_environment, engine=engine) as (session, query, config_obj):
        api_key = getattr(config_obj, "GOOGLE_DRIVE_API_KEY", None)

        # List all PDFs in the folder
        try:
            pdf_files = _list_gdrive_folder_pdfs(folder_id, api_key)
            logging.info(f"Found {len(pdf_files)} PDF files in folder")
        except ValueError as e:
            raise

        if not pdf_files:
            raise ValueError("No PDF files found in the Google Drive folder.")

        # Update progress
        task_status.progress(0, len(pdf_files))

        # Create a project for each PDF
        created_projects = []
        for idx, pdf_file in enumerate(pdf_files):
            file_id = pdf_file["id"]
            file_name = pdf_file["name"]

            # Use filename (without extension) as the title
            title = Path(file_name).stem
            logging.info(f"Creating project for: {title} ({file_name})")

            # Get download URL
            download_url = _get_gdrive_file_download_url(file_id)

            # Create project using the existing logic
            try:
                create_project_inner(
                    display_title=title,
                    pdf_url=download_url,
                    upload_folder=upload_folder,
                    app_environment=app_environment,
                    creator_id=creator_id,
                    task_status=TaskStatus(),  # Use a dummy status for individual projects
                    engine=engine,
                )
                created_projects.append(title)
                logging.info(f"Successfully created project: {title}")
            except Exception as e:
                logging.error(f"Failed to create project for {title}: {e}")
                # Continue with other files even if one fails

            # Update progress
            task_status.progress(idx + 1, len(pdf_files))

        # Return summary
        success_msg = (
            f"Created {len(created_projects)} projects from {len(pdf_files)} PDFs"
        )
        logging.info(success_msg)
        task_status.success(len(created_projects), success_msg)


@app.task(bind=True)
def create_projects_from_gdrive_folder(
    self,
    *,
    folder_url: str,
    upload_folder: str,
    app_environment: str,
    creator_id: int,
):
    """Create multiple projects from PDFs in a Google Drive folder.

    For argument details, see `create_projects_from_gdrive_folder_inner`.
    """
    task_status = CeleryTaskStatus(self)
    create_projects_from_gdrive_folder_inner(
        folder_url=folder_url,
        upload_folder=upload_folder,
        app_environment=app_environment,
        creator_id=creator_id,
        task_status=task_status,
    )
