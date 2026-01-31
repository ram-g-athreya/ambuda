"""Routes for reviewing suggestions from non-P1 users."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from ambuda import database as db
from ambuda import queries as q
from ambuda.models.proofing import SuggestionStatus
from ambuda.utils.diff import revision_diff
from ambuda.utils.revisions import add_revision
from ambuda.views.proofing.decorators import p1_required

bp = Blueprint("suggestions", __name__)


PAGE_SIZE = 100


@bp.route("/suggestions/")
@p1_required
def index():
    """List suggestions, filtered by status, with cursor-based pagination."""
    status_filter = request.args.get("status", SuggestionStatus.PENDING)
    try:
        SuggestionStatus(status_filter)
    except ValueError:
        status_filter = SuggestionStatus.PENDING

    cursor = request.args.get("before", type=int)

    session = q.get_session()
    stmt = (
        select(db.Suggestion)
        .filter(db.Suggestion.status == status_filter)
        .order_by(db.Suggestion.id.desc())
    )
    if cursor is not None:
        stmt = stmt.filter(db.Suggestion.id < cursor)
    stmt = stmt.limit(PAGE_SIZE + 1)

    results = list(session.scalars(stmt).all())
    has_next = len(results) > PAGE_SIZE
    suggestions = results[:PAGE_SIZE]

    next_cursor = suggestions[-1].id if has_next and suggestions else None

    # For each suggestion, compute staleness and diff against the base revision
    for s in suggestions:
        page = s.page
        latest_revision = page.revisions[-1] if page.revisions else None
        s._is_stale = latest_revision is None or latest_revision.id != s.revision_id
        base_content = s.revision.content if s.revision else ""
        s._diff = revision_diff(base_content, s.content)

    return render_template(
        "proofing/suggestions.html",
        suggestions=suggestions,
        status_filter=status_filter,
        SuggestionStatus=SuggestionStatus,
        next_cursor=next_cursor,
    )


@bp.route("/suggestions/<int:id>/accept", methods=["POST"])
@p1_required
def accept(id):
    """Accept a suggestion, creating a new revision."""
    session = q.get_session()
    suggestion = session.get(db.Suggestion, id)
    if not suggestion:
        flash("Suggestion not found.", "error")
        return redirect(url_for("proofing.suggestions.index"))

    if suggestion.status != SuggestionStatus.PENDING:
        flash("This suggestion has already been processed.", "error")
        return redirect(url_for("proofing.suggestions.index"))

    page = suggestion.page
    latest_revision = page.revisions[-1] if page.revisions else None

    if latest_revision is None or latest_revision.id != suggestion.revision_id:
        flash(
            "This suggestion is based on an outdated revision. "
            "Please review the page manually before accepting.",
            "error",
        )
        return redirect(url_for("proofing.suggestions.index"))

    from flask_login import current_user

    add_revision(
        page,
        summary=f"Accepted suggestion: {suggestion.explanation}"
        if suggestion.explanation
        else "Accepted suggestion",
        content=suggestion.content,
        status=latest_revision.status.name,
        version=page.version,
        author_id=current_user.id,
    )

    suggestion.status = SuggestionStatus.ACCEPTED
    session.add(suggestion)
    session.commit()

    flash("Suggestion accepted and revision created.", "success")
    return redirect(url_for("proofing.suggestions.index"))


@bp.route("/suggestions/<int:id>/reject", methods=["POST"])
@p1_required
def reject(id):
    """Reject a suggestion."""
    session = q.get_session()
    suggestion = session.get(db.Suggestion, id)
    if not suggestion:
        flash("Suggestion not found.", "error")
        return redirect(url_for("proofing.suggestions.index"))

    if suggestion.status != SuggestionStatus.PENDING:
        flash("This suggestion has already been processed.", "error")
        return redirect(url_for("proofing.suggestions.index"))

    suggestion.status = SuggestionStatus.REJECTED
    session.add(suggestion)
    session.commit()

    flash("Suggestion rejected.", "success")
    return redirect(url_for("proofing.suggestions.index"))
