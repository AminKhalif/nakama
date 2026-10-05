"""Gateway app operations over the standalone scheduling service."""
from nakama.contracts import Operation
from gateway.wire import AppError

from .models import SchedulingError, TimeWindow
from .service import MeetingService


class CalendarAdapter:
    app_id = 'calendar'

    def __init__(self, service: MeetingService):
        self.service = service

    def operations(self):
        time = {'type': 'string', 'minLength': 1}
        bounds = {'start': time, 'end': time}
        def operation(name, scope, description, properties, required, handler):
            def invoke(context, data):
                try:
                    return handler(context, data)
                except SchedulingError as exc:
                    raise AppError('scheduling_error', str(exc), 409) from exc
            return Operation(name, 'app.calendar:' + scope, description,
                {'type': 'object', 'properties': properties, 'required': required,
                 'additionalProperties': False}, invoke)
        return (
            operation('availability', 'availability', 'Read shared free time without event details.',
                bounds, ['start', 'end'], lambda c, d: self.service.availability(c.caller_id, c.peer_id,
                    TimeWindow.parse(d['start'], d['end']))),
            operation('find_slots', 'availability', 'Find meeting times within both owners\' shared windows.',
                {**bounds, 'duration_minutes': {'type': 'integer', 'minimum': 1, 'maximum': 480},
                 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}}, ['start', 'end'],
                lambda c, d: self.service.find_slots(c.caller_id, c.peer_id,
                    TimeWindow.parse(d['start'], d['end']), d.get('duration_minutes', 30), d.get('limit', 10))),
            operation('propose', 'propose', 'Propose a meeting; creates no calendar event.',
                {**bounds, 'summary': {'type': 'string', 'minLength': 1, 'maxLength': 200}},
                ['start', 'end', 'summary'], lambda c, d: self.service.propose(c.caller_id, c.peer_id,
                    TimeWindow.parse(d['start'], d['end']), d['summary'])),
            operation('status', 'propose', 'Read this connection\'s meeting proposal.',
                {'proposal_id': time}, ['proposal_id'],
                lambda c, d: self.service.status(c.caller_id, c.peer_id, d['proposal_id'])),
            operation('book', 'book', 'Book an exact proposal only after both owners approve it.',
                {'proposal_id': time}, ['proposal_id'],
                lambda c, d: self.service.book(c.caller_id, c.peer_id, d['proposal_id'])),
        )
