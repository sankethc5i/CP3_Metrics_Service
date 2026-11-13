"""Relative date resolution using only the frozen catalog date."""

from datetime import date, timedelta

from app.config import AS_OF_DATE
from app.llm.schemas import TimeRange


def resolve_dates(spec: TimeRange) -> tuple[str,str]:
    """Return inclusive start and exclusive end; never read the wall clock."""
    anchor = AS_OF_DATE
    month = anchor.replace(day=1)
    quarter = date(anchor.year,((anchor.month-1)//3)*3+1,1)
    year = date(anchor.year,1,1)
    periods = {
        "all_time":(date(1900,1,1),anchor),
        "this_month":(month,anchor),
        "last_month":((month-timedelta(days=1)).replace(day=1),month),
        "this_quarter":(quarter,anchor),
        "last_quarter":(date((quarter-timedelta(days=1)).year,((quarter-timedelta(days=1)).month-1)//3*3+1,1),quarter),
        "this_year":(year,anchor),
        "last_year":(date(anchor.year-1,1,1),year),
        "last_30_days":(anchor-timedelta(days=30),anchor),
    }
    if spec.relative:
        start,end = periods[spec.relative]
    else:
        start,end = date.fromisoformat(spec.start or ""),date.fromisoformat(spec.end or "")
        if start >= end:
            raise ValueError("Start must precede end")
    # Empty current month on a snapshot boundary is a legitimate empty result.
    return start.isoformat(),min(end,anchor).isoformat()
