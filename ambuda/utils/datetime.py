from datetime import datetime, timezone


def utc_datetime_timestamp() -> str:
    """A simple UTC timestamp for stamping resources (e.g. file downloads)"""
    now_aware = datetime.now(timezone.utc)
    return now_aware.strftime("%Y-%m-%d %H:%M:%S UTC")
