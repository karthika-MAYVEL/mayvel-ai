from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional

def resolve_time_window(window: dict | None) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Resolves a time window dict into start and end UTC datetime bounds"""
    if not window:
        return None, None

    dt_now = datetime.now(tz=timezone.utc)
    
    def start_of_day(dt: datetime) -> datetime:
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    def start_of_month(dt: datetime) -> datetime:
        return start_of_day(dt.replace(day=1))
        
    def start_of_year(dt: datetime) -> datetime:
        return start_of_day(dt.replace(month=1, day=1))

    mode = window.get("mode")
    if mode == "absolute":
        gte_str = window.get("gte")
        lt_str = window.get("lt")
        start = datetime.fromisoformat(gte_str.replace("Z", "+00:00")) if gte_str else None
        end = datetime.fromisoformat(lt_str.replace("Z", "+00:00")) if lt_str else None
        return start, end

    k = window.get("kind")
    if k == "lastNDays":
        amount = window.get("amount", 7)
        start = dt_now - timedelta(days=amount)
        return start, dt_now
    elif k == "lastNYears":
        amount = window.get("amount", 1)
        start = dt_now.replace(year=dt_now.year - amount)
        return start, dt_now
    elif k == "today":
        start = start_of_day(dt_now)
        end = start + timedelta(days=1)
        return start, end
    elif k == "thisWeek":
        days_since_monday = dt_now.weekday()
        start = start_of_day(dt_now - timedelta(days=days_since_monday))
        end = start + timedelta(days=7)
        return start, end
    elif k == "thisMonth":
        start = start_of_month(dt_now)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end
    elif k == "lastMonth":
        curr_month_start = start_of_month(dt_now)
        if curr_month_start.month == 1:
            start = curr_month_start.replace(year=curr_month_start.year - 1, month=12)
        else:
            start = curr_month_start.replace(month=curr_month_start.month - 1)
        return start, curr_month_start
    elif k == "thisYear":
        start = start_of_year(dt_now)
        end = start.replace(year=start.year + 1)
        return start, end
    elif k == "nextNDays":
        amount = window.get("amount", 7)
        start = dt_now
        end = dt_now + timedelta(days=amount)
        return start, end
    elif k in ("YTD", "overdue"):
        return None, None

    raise ValueError(f"Unknown time_window kind: {k}")
