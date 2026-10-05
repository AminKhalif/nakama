"""Calendar providers receive account bindings from the host, never agent input."""
from dataclasses import dataclass
import hashlib
import threading
from typing import Any, Protocol, Sequence

from .models import SchedulingError, TimeWindow


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str


class CalendarProvider(Protocol):
    def busy(self, window: TimeWindow) -> Sequence[TimeWindow]: ...

    def create_event(self, *, request_id: str, window: TimeWindow,
                     summary: str, attendee: str) -> CalendarEvent:
        """Create one organizer event; repeated request IDs must be idempotent."""
        ...


class MemoryCalendar:
    """Local demo/test calendar. It does not contact an external account."""
    def __init__(self, busy: Sequence[TimeWindow] = ()):
        self._busy = list(busy)
        self.events = {}
        self._lock = threading.RLock()

    def busy(self, window):
        with self._lock:
            return tuple(item for item in self._busy if item.overlaps(window))

    def create_event(self, *, request_id, window, summary, attendee):
        with self._lock:
            contents = (window, summary, attendee)
            if request_id in self.events:
                if self.events[request_id] != contents:
                    raise SchedulingError('request id reused for a different event')
                return CalendarEvent(request_id)
            self.events[request_id] = contents
            self._busy.append(window)
            return CalendarEvent(request_id)


class GoogleCalendar:
    """Adapter over an authorized Google Calendar v3 discovery client.

    The host owns OAuth, token refresh, credentials, and client HTTP timeouts.
    Use a read-capable client for busy() and optionally a separate write client.
    """
    def __init__(self, service: Any, calendar_id: str = 'primary', *, write_service: Any = None):
        if not isinstance(calendar_id, str) or not calendar_id:
            raise ValueError('calendar_id is required')
        self._service = service
        self._write_service = write_service
        self._calendar_id = calendar_id

    def busy(self, window):
        body = {'timeMin': window.as_dict()['start'], 'timeMax': window.as_dict()['end'],
                'timeZone': 'UTC', 'items': [{'id': self._calendar_id}]}
        try:
            response = self._service.freebusy().query(body=body).execute()
            calendar = response['calendars'][self._calendar_id]
            if calendar.get('errors') or not isinstance(calendar['busy'], list):
                raise ValueError('free/busy unavailable')
            return tuple(TimeWindow.parse(item['start'], item['end']) for item in calendar['busy'])
        except Exception as exc:
            # Do not include provider response bodies, event data, or tokens in errors.
            raise SchedulingError('calendar availability could not be retrieved') from exc

    def create_event(self, *, request_id, window, summary, attendee):
        if self._write_service is None:
            raise SchedulingError('no calendar write client configured')
        # Google event IDs permit the base32hex alphabet; hexadecimal is a subset.
        event_id = hashlib.sha256(request_id.encode()).hexdigest()
        times = window.as_dict()
        body = {'id': event_id, 'summary': summary,
                'start': {'dateTime': times['start']}, 'end': {'dateTime': times['end']},
                'attendees': [{'email': attendee}]}
        try:
            response = self._write_service.events().insert(
                calendarId=self._calendar_id, body=body, sendUpdates='all').execute()
        except Exception as exc:
            if getattr(getattr(exc, 'resp', None), 'status', None) != 409:
                raise SchedulingError('calendar booking failed; retry the same proposal') from exc
            try:
                response = self._write_service.events().get(
                    calendarId=self._calendar_id, eventId=event_id).execute()
            except Exception as lookup:
                raise SchedulingError('calendar booking could not be reconciled') from lookup
        if (response.get('id') != event_id or response.get('status') == 'cancelled'
                or response.get('summary') != summary
                or response.get('start', {}).get('dateTime') is None
                or response.get('end', {}).get('dateTime') is None):
            raise SchedulingError('calendar returned an unexpected event')
        actual = TimeWindow.parse(response['start']['dateTime'], response['end']['dateTime'])
        if actual != window or attendee not in {a.get('email') for a in response.get('attendees', [])}:
            raise SchedulingError('calendar returned an unexpected event')
        return CalendarEvent(event_id)
