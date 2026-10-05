"""Timezone-aware scheduling values. Calendar details never enter availability."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


class SchedulingError(ValueError):
    """A scheduling operation could not safely proceed."""


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError('timezone required')
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise SchedulingError('timestamps must include a UTC offset') from exc


@dataclass(frozen=True, order=True)
class TimeWindow:
    start: datetime
    end: datetime

    def __post_init__(self):
        for field in ('start', 'end'):
            value = getattr(self, field)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise SchedulingError('time windows require timezone-aware datetimes')
            object.__setattr__(self, field, value.astimezone(timezone.utc))
        if self.start >= self.end:
            raise SchedulingError('window end must follow start')

    @classmethod
    def parse(cls, start: str, end: str) -> 'TimeWindow':
        return cls(timestamp(start), timestamp(end))

    def as_dict(self) -> dict[str, str]:
        return {key: getattr(self, key).isoformat().replace('+00:00', 'Z')
                for key in ('start', 'end')}

    def overlaps(self, other: 'TimeWindow') -> bool:
        return self.start < other.end and other.start < self.end


def merge(windows: Iterable[TimeWindow]) -> tuple[TimeWindow, ...]:
    result = []
    for window in sorted(windows):
        if result and window.start <= result[-1].end:
            previous = result.pop()
            result.append(TimeWindow(previous.start, max(previous.end, window.end)))
        else:
            result.append(window)
    return tuple(result)


def available(query: TimeWindow, sharing: Iterable[TimeWindow],
              busy: Iterable[TimeWindow]) -> tuple[TimeWindow, ...]:
    """Subtract busy intervals only inside explicitly shared windows."""
    blocks = merge(busy)
    result = []
    for shared in merge(sharing):
        start, end = max(query.start, shared.start), min(query.end, shared.end)
        if start >= end:
            continue
        cursor = start
        for block in blocks:
            if block.end <= cursor or block.start >= end:
                continue
            if cursor < block.start:
                result.append(TimeWindow(cursor, min(end, block.start)))
            cursor = max(cursor, block.end)
            if cursor >= end:
                break
        if cursor < end:
            result.append(TimeWindow(cursor, end))
    return tuple(result)


def shared_slots(left: Iterable[TimeWindow], right: Iterable[TimeWindow],
                 duration_minutes: int, limit: int = 10) -> tuple[TimeWindow, ...]:
    if type(duration_minutes) is not int or not 1 <= duration_minutes <= 480:
        raise SchedulingError('duration_minutes must be between 1 and 480')
    if type(limit) is not int or not 1 <= limit <= 20:
        raise SchedulingError('limit must be between 1 and 20')
    intersections = []
    for a in merge(left):
        for b in merge(right):
            start, end = max(a.start, b.start), min(a.end, b.end)
            if start < end:
                intersections.append(TimeWindow(start, end))
    duration = timedelta(minutes=duration_minutes)
    result = []
    for window in merge(intersections):
        cursor = window.start
        while cursor + duration <= window.end and len(result) < limit:
            result.append(TimeWindow(cursor, cursor + duration))
            cursor += duration
        if len(result) == limit:
            break
    return tuple(result)
