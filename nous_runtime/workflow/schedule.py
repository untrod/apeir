"""UTC calendar calculations only; WorkflowStore owns trigger/run identity.

Five numeric cron fields use conventional day-of-month/day-of-week OR semantics.
There are no commands, time zones, executable expressions or authorization here.
"""

from datetime import datetime, timedelta, timezone
import re

from croniter import CroniterBadDateError, CroniterBadCronError, croniter


def cron_expression(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 128
        or not re.fullmatch(r"[0-9*/,\- ]+", value)
        or len(value.split()) != 5
    ):
        raise ValueError(
            "Cron requires five numeric UTC fields (at most 128 characters)"
        )
    expression = " ".join(value.split())
    try:
        # Bound sparse calendar search, including impossible dates such as Feb 30.
        iterator = croniter(
            expression,
            datetime(2000, 1, 1, tzinfo=timezone.utc),
            max_years_between_matches=8,
        )
        iterator.get_next(datetime)
    except (CroniterBadCronError, CroniterBadDateError, ValueError, KeyError) as exc:
        raise ValueError("Invalid or unsupported UTC Cron expression") from exc
    return expression


def latest_occurrence(
    expression: str, now: datetime, created_at: datetime
) -> str | None:
    """Coalesce missed ticks to the latest due minute; never backfill a burst."""
    if any(
        value.tzinfo is None or value.utcoffset() != timedelta(0)
        for value in (now, created_at)
    ):
        raise ValueError("Cron clock and creation time must be explicit UTC")
    expression = cron_expression(expression)
    try:
        occurrence = croniter(
            expression,
            now + timedelta(microseconds=1),
            max_years_between_matches=8,
        ).get_prev(datetime)
    except CroniterBadDateError:
        return None
    if occurrence < created_at:
        return None
    return occurrence.isoformat(timespec="microseconds")
