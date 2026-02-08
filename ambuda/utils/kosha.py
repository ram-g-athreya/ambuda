from pathlib import Path

from vidyut.kosha import Kosha


def get_kosha(vidyut_data_dir: str):
    """Load a kosha (no singleton, for throwaway instances in celery)."""
    return Kosha(Path(vidyut_data_dir) / "kosha")
