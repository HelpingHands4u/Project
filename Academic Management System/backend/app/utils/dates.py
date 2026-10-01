"""Use the university's calendar date, independent of server location."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo


def campus_today():
    return datetime.now(ZoneInfo(os.getenv("CAMPUS_TIMEZONE", "Asia/Kolkata"))).date()
