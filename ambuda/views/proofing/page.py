"""Routes related to project pages.

The main route here is `edit`, which defines the page editor and the edit flow.
"""

import uuid
from dataclasses import dataclass

from flask import (
    Blueprint,
    current_app,
    flash,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_babel import lazy_gettext as _l
from flask_login import current_user
from flask_wtf import FlaskForm
from werkzeug.exceptions import abort
from wtforms import HiddenField, RadioField, StringField
from wtforms.validators import DataRequired, ValidationError
from wtforms.widgets import TextArea

from ambuda import database as db
from ambuda import queries as q
from ambuda.enums import SitePageStatus
from ambuda.utils import project_utils
from ambuda.utils.diff import revision_diff
from ambuda.utils.revisions import EditError, add_revision
from ambuda.utils.project_structuring import ProofPage
from ambuda.utils.xml_validation import validate_proofing_xml
from ambuda.views.site import bp as site

bp = Blueprint("page", __name__)


def page_xml_validator(form, field):
    errors = validate_proofing_xml(field.data)
    if errors:
        messages = [error.message for error in errors]
        raise ValidationError("; ".join(messages))


@dataclass
class PageContext:
    """A page, its project, and some navigation data."""

    #: The current project.
    project: db.Project
    #: The current page.
    cur: db.Page
    #: The page before `cur`, if it exists.
    prev: db.Page | None
    #: The page after `cur`, if it exists.
    next: db.Page | None
    #: The number of pages in this project.
    num_pages: int


class EditPageForm(FlaskForm):
    #: An optional summary that describes the revision.
    summary = StringField(_l("Edit summary (optional)"))
    #: The page version. Versions are monotonically increasing: if A < B, then
    #: A is older than B.
    version = HiddenField(_l("Page version"))
    #: The page content.
    content = StringField(
        _l("Page content"),
        widget=TextArea(),
        validators=[DataRequired(), page_xml_validator],
    )
    #: The page status.
    status = RadioField(
        _l("Status"),
        choices=[
            (SitePageStatus.R0.value, _l("Needs work")),
            (SitePageStatus.R1.value, _l("Proofed once")),
            (SitePageStatus.R2.value, _l("Proofed twice")),
            (SitePageStatus.SKIP.value, _l("Not relevant")),
        ],
    )


def _get_page_context(project_slug: str, page_slug: str) -> PageContext | None:
    """Get the previous, current, and next pages for the given project.

    :param project_slug: slug for the current project
    :param page_slug: slug for a page within the current project.
    :return: a `PageContext` if the project and page can be found, else ``None``.
    """
    project_ = q.project(project_slug)
    if project_ is None:
        return None

    pages = project_.pages
    found = False
    i = 0
    for i, s in enumerate(pages):
        if s.slug == page_slug:
            found = True
            break

    if not found:
        return None

    prev = pages[i - 1] if i > 0 else None
    cur = pages[i]
    next = pages[i + 1] if i < len(pages) - 1 else None
    return PageContext(
        project=project_, cur=cur, prev=prev, next=next, num_pages=len(pages)
    )


def _get_page_number(project_: db.Project, page_: db.Page) -> str:
    """Get the page number for the given page.

    We define page numbers through a page spec. For now, just interpret the
    full page spec. In the future, we might store this in its own column.
    """
    if not project_.page_numbers:
        return page_.slug

    page_rules = project_utils.parse_page_number_spec(project_.page_numbers)
    page_titles = project_utils.apply_rules(len(project_.pages), page_rules)
    for title, cur in zip(page_titles, project_.pages):
        if cur.id == page_.id:
            return title

    # We shouldn't reach this case, but if we do, reuse the page's slug.
    return page_.slug


def _get_image_url(project: db.Project, page: db.Page) -> str:
    """Handler for getting the image URL (S3 migration in progress.)"""
    if current_app.debug:
        return url_for(
            "site.page_image", project_slug=project.slug, page_slug=page.slug
        )
    else:
        return page.cloudfront_url(current_app.config.get("CLOUDFRONT_BASE_URL", ""))


def _get_page_data_dict(ctx: PageContext, project: db.Project) -> dict:
    """Return page data as a plain dict, shared between the HTML view and the JSON API."""
    cur = ctx.cur
    has_edits = bool(cur.revisions)
    content = ""
    if has_edits:
        latest_revision = cur.revisions[-1]
        content = ProofPage.from_content_and_page_id(
            latest_revision.content, cur.id
        ).to_xml_string()

    status_names = {s.id: s.name for s in q.page_statuses()}
    status = status_names[cur.status_id]
    is_r0 = cur.status.name == SitePageStatus.R0

    return {
        "projectSlug": project.slug,
        "projectTitle": project.display_title,
        "pageSlug": cur.slug,
        "prevSlug": ctx.prev.slug if ctx.prev else None,
        "nextSlug": ctx.next.slug if ctx.next else None,
        "pageNumber": _get_page_number(project, cur),
        "numPages": ctx.num_pages,
        "status": status,
        "version": cur.version,
        "hasEdits": has_edits,
        "isR0": is_r0,
        "content": content,
        "imageUrl": _get_image_url(project, cur),
        "ocrBoundingBoxes": cur.ocr_bounding_boxes or "",
        "editUrl": url_for(
            "proofing.page.edit",
            project_slug=project.slug,
            page_slug=cur.slug,
        ),
    }


@bp.route("/<project_slug>/<page_slug>/")
def edit(project_slug, page_slug):
    """Display the page editor."""
    ctx = _get_page_context(project_slug, page_slug)
    if ctx is None:
        abort(404)
    assert ctx

    data = _get_page_data_dict(ctx, ctx.project)
    data["canSaveDirectly"] = current_user.is_authenticated and current_user.is_p1

    cur = ctx.cur
    form = EditPageForm()
    form.version.data = data["version"]
    form.status.data = data["status"]
    if data["hasEdits"]:
        form.content.data = data["content"]

    return render_template(
        "proofing/pages/edit.html",
        conflict=None,
        cur=ctx.cur,
        form=form,
        page_state=data,
        page_context=ctx,
        project=ctx.project,
    )


@bp.route("/<project_slug>/<page_slug>/", methods=["POST"])
def edit_post(project_slug, page_slug):
    """Submit changes through the page editor.

    Since `edit` is public on GET and needs auth on `POST`, it's cleaner to
    separate the logic here into two views.
    """
    ctx = _get_page_context(project_slug, page_slug)
    if ctx is None:
        abort(404)
    assert ctx

    cur = ctx.cur
    form = EditPageForm()
    conflict = None
    can_save_directly = current_user.is_authenticated and current_user.is_p1

    if form.validate_on_submit():
        # `new_content` is already validated through EditPageForm.
        new_content = form.content.data

        if can_save_directly:
            # P1+ users: existing direct-save flow.
            cur_page = ctx.cur
            if cur_page.revisions:
                cur_content = cur_page.revisions[-1].content
            else:
                cur_content = None
            content_has_changed = cur_content != new_content

            status_has_changed = cur_page.status.name != form.status.data
            has_changed = content_has_changed or status_has_changed
            try:
                if has_changed:
                    new_version = add_revision(
                        cur,
                        summary=form.summary.data,
                        content=form.content.data,
                        status=form.status.data,
                        version=int(form.version.data),
                        author_id=current_user.id,
                    )
                    form.version.data = new_version
                    flash("Saved changes.", "success")
                else:
                    flash("Skipped save. (No changes made.)", "success")
            except EditError:
                # FIXME: in the future, use a proper edit conflict view.
                flash("Edit conflict. Please incorporate the changes below:")
                conflict = cur.revisions[-1]
                form.version.data = cur.version
        else:
            # Non-P1 users (including anonymous): create a suggestion.
            latest_revision = cur.revisions[-1] if cur.revisions else None
            if latest_revision is None:
                flash("Cannot suggest edits on a page with no revisions.", "error")
            else:
                session = q.get_session()
                suggestion = db.Suggestion(
                    project_id=ctx.project.id,
                    page_id=cur.id,
                    revision_id=latest_revision.id,
                    user_id=current_user.id if current_user.is_authenticated else None,
                    batch_id=str(uuid.uuid4()),
                    content=new_content,
                    explanation=request.form.get("explanation", ""),
                )
                session.add(suggestion)
                session.commit()
                flash("Your suggestion has been submitted for review.", "success")
    else:
        flash("Sorry, your changes have one or more errors.", "error")

    data = _get_page_data_dict(ctx, ctx.project)
    data["canSaveDirectly"] = can_save_directly
    data["hasEdits"] = True

    return render_template(
        "proofing/pages/edit.html",
        conflict=conflict,
        cur=ctx.cur,
        form=form,
        page_state=data,
        page_context=ctx,
        project=ctx.project,
    )


@site.route("/static/uploads/<project_slug>/pages/<page_slug>.jpg")
def page_image(project_slug, page_slug):
    """(Debug only) Serve an image from the filesystem.

    In production, we serve images directly from Cloudfront.
    """
    assert current_app.debug

    project = q.project(project_slug)
    if not project:
        return None

    page = q.page(project.id, page_slug)
    if not page:
        return None

    s3_path = page.s3_path(current_app.config["S3_BUCKET"])
    local_path = s3_path._debug_local_path()
    if not local_path:
        return None

    return send_file(local_path)


@bp.route("/<project_slug>/<page_slug>/history")
def history(project_slug, page_slug):
    """View the full revision history for the given page."""
    ctx = _get_page_context(project_slug, page_slug)
    if ctx is None:
        abort(404)

    assert ctx
    return render_template(
        "proofing/pages/history.html",
        project=ctx.project,
        cur=ctx.cur,
        prev=ctx.prev,
        next=ctx.next,
    )


@bp.route("/<project_slug>/<page_slug>/revision/<revision_id>")
def revision(project_slug, page_slug, revision_id):
    """View a specific revision for some page."""
    ctx = _get_page_context(project_slug, page_slug)
    if ctx is None:
        abort(404)

    assert ctx
    cur = ctx.cur
    prev_revision = None
    cur_revision = None
    for r in cur.revisions:
        if str(r.id) == revision_id:
            cur_revision = r
            break
        else:
            prev_revision = r

    if not cur_revision:
        abort(404)

    if prev_revision:
        diff = revision_diff(prev_revision.content, cur_revision.content)
    else:
        diff = revision_diff("", cur_revision.content)

    return render_template(
        "proofing/pages/revision.html",
        project=ctx.project,
        cur=cur,
        prev=ctx.prev,
        next=ctx.next,
        revision=cur_revision,
        diff=diff,
    )
