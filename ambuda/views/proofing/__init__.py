"""Everything related to our proofing and transcription work."""

from . import main, page, project, publish, suggestions, tagging, talk, tutorial, user

__all__ = ["bp", "user_bp"]


bp = main.bp
bp.register_blueprint(project.bp)
bp.register_blueprint(publish.bp)
bp.register_blueprint(page.bp)
bp.register_blueprint(suggestions.bp)
bp.register_blueprint(tagging.bp, url_prefix="/texts")
bp.register_blueprint(talk.bp)
bp.register_blueprint(tutorial.bp)

# Export user blueprint separately to be registered at app level
user_bp = user.bp
