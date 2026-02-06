"""Background tasks for running batch LLM prompts and storing results as suggestions."""

import logging

from celery.result import AsyncResult

from ambuda import consts
from ambuda import database as db
from ambuda.models.proofing import SuggestionStatus
from ambuda.tasks import app
from ambuda.tasks.utils import get_db_session
from ambuda.utils import llm_structuring
from ambuda.utils.xml_validation import validate_proofing_xml, ValidationType

LOG = logging.getLogger(__name__)


@app.task(bind=True)
def run_batch_llm(
    self,
    *,
    app_env: str,
    project_slug: str,
    page_slugs: list[str],
    prompt_template: str,
    batch_id: str,
):
    """Run an LLM prompt over all pages in a single API call, then create suggestions."""
    with get_db_session(app_env) as (session, query, config_obj):
        bot_user = query.user(consts.BOT_USERNAME)
        if not bot_user:
            raise ValueError(f'User "{consts.BOT_USERNAME}" is not defined.')

        api_key = config_obj.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        project = query.project(project_slug)

        # Gather page contents.
        page_contents = {}
        page_meta = {}  # slug -> (page, latest_revision)
        for slug in page_slugs:
            page = query.page(project.id, slug)
            latest_revision = (
                session.query(db.Revision)
                .filter(db.Revision.page_id == page.id)
                .order_by(db.Revision.created_at.desc())
                .first()
            )
            if latest_revision and latest_revision.content:
                page_contents[slug] = latest_revision.content
                page_meta[slug] = (page, latest_revision)

        if not page_contents:
            raise ValueError(f"No pages with content found for {project_slug}")

        # Single LLM call for all pages.
        results = llm_structuring.run_batch(page_contents, api_key, prompt_template)

        explanation = prompt_template[:100].strip()
        if len(prompt_template) > 100:
            explanation += "..."

        created = 0
        skipped = 0
        for slug in page_slugs:
            if slug not in results:
                LOG.warning("LLM returned no output for page %s/%s", project_slug, slug)
                skipped += 1
                continue

            llm_output = results[slug]
            validation_errors = validate_proofing_xml(llm_output)
            errors = [r for r in validation_errors if r.type == ValidationType.ERROR]
            if errors:
                error_msgs = "; ".join(r.message for r in errors[:5])
                LOG.warning(
                    "LLM output failed validation for %s/%s: %s",
                    project_slug,
                    slug,
                    error_msgs,
                )
                skipped += 1
                continue

            page, latest_revision = page_meta[slug]
            suggestion = db.Suggestion(
                project_id=project.id,
                page_id=page.id,
                revision_id=latest_revision.id,
                user_id=bot_user.id,
                batch_id=batch_id,
                content=llm_output,
                explanation=explanation,
                status=SuggestionStatus.PENDING,
            )
            session.add(suggestion)
            created += 1

        session.commit()
        return {"created": created, "skipped": skipped, "total": len(page_slugs)}


def run_batch_llm_for_project(
    app_env: str,
    project: db.Project,
    prompt_template: str,
    page_slugs: list[str],
    batch_id: str,
) -> AsyncResult | None:
    """Dispatch a single Celery task to process all pages in one LLM call."""
    if not page_slugs:
        return None

    return run_batch_llm.delay(
        app_env=app_env,
        project_slug=project.slug,
        page_slugs=page_slugs,
        prompt_template=prompt_template,
        batch_id=batch_id,
    )
