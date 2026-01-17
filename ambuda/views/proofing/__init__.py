"""Everything related to our proofing and transcription work."""

from . import main, page, project, tagging, talk, user

__all__ = ["bp", "user_bp"]


bp = main.bp
bp.register_blueprint(project.bp)
bp.register_blueprint(page.bp)
bp.register_blueprint(tagging.bp, url_prefix="/texts")
bp.register_blueprint(talk.bp)

# Export user blueprint separately to be registered at app level
user_bp = user.bp
