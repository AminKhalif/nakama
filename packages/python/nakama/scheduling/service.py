"""Provider-independent meeting negotiation and explicit owner approval."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time
from typing import Callable, Mapping
import uuid

from .models import SchedulingError, TimeWindow, available, shared_slots
from .providers import CalendarProvider
from .store import ProposalStore


@dataclass(frozen=True)
class CalendarBinding:
    """An authenticated host links an agent to an owner and a calendar account."""
    owner_id: str
    provider: CalendarProvider
    attendee_address: str
    sharing_windows: tuple[TimeWindow, ...] = ()
    # Change binding_id when relinking an account, even for the same owner.
    binding_id: str = ''

    def __post_init__(self):
        if not self.owner_id or not self.attendee_address or not self.binding_id:
            raise ValueError('owner_id, attendee_address, and binding_id are required')
        object.__setattr__(self, 'sharing_windows', tuple(self.sharing_windows))


class MeetingService:
    def __init__(self, bindings: Mapping[str, CalendarBinding], store: ProposalStore,
                 authorize: Callable[[str, str, str], None], *, clock: Callable[[], float] = time.time):
        self._bindings = dict(bindings)
        self._store = store
        self._authorize = authorize
        self._clock = clock

    def _pair(self, caller_id, peer_id):
        if caller_id == peer_id:
            raise SchedulingError('meeting requires two distinct agents')
        try:
            return self._bindings[caller_id], self._bindings[peer_id]
        except KeyError:
            raise SchedulingError('both agents need host-linked calendars') from None

    def _free(self, binding, query):
        if not any(query.overlaps(window) for window in binding.sharing_windows):
            return ()
        return available(query, binding.sharing_windows, binding.provider.busy(query))

    def _query(self, query):
        if query.end - query.start > timedelta(days=31):
            raise SchedulingError('availability queries are limited to 31 days')
        if query.start < datetime.fromtimestamp(self._clock(), timezone.utc):
            raise SchedulingError('scheduling windows must be in the future')

    def availability(self, caller_id: str, peer_id: str, query: TimeWindow):
        self._authorize(caller_id, peer_id, 'app.calendar:availability')
        self._query(query)
        _, peer = self._pair(caller_id, peer_id)
        return {'windows': [window.as_dict() for window in self._free(peer, query)]}

    def find_slots(self, caller_id: str, peer_id: str, query: TimeWindow,
                   duration_minutes: int = 30, limit: int = 10):
        self._authorize(caller_id, peer_id, 'app.calendar:availability')
        self._query(query)
        caller, peer = self._pair(caller_id, peer_id)
        slots = shared_slots(self._free(caller, query), self._free(peer, query), duration_minutes, limit)
        return {'slots': [slot.as_dict() for slot in slots]}

    def propose(self, caller_id: str, peer_id: str, window: TimeWindow, summary: str):
        self._authorize(caller_id, peer_id, 'app.calendar:propose')
        self._authorize(caller_id, peer_id, 'app.calendar:availability')
        self._query(window)
        if window.end - window.start > timedelta(hours=8):
            raise SchedulingError('meetings are limited to eight hours')
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 200:
            raise SchedulingError('summary must contain 1 to 200 characters')
        caller, peer = self._pair(caller_id, peer_id)
        if caller.owner_id == peer.owner_id:
            raise SchedulingError('this workflow requires two distinct owners')
        if any(not any(free.start <= window.start and free.end >= window.end
                        for free in self._free(binding, window)) for binding in (caller, peer)):
            raise SchedulingError('meeting time is no longer available')
        proposal = {'id': 'meeting_' + uuid.uuid4().hex, 'caller_id': caller_id, 'peer_id': peer_id,
                    **window.as_dict(), 'summary': summary.strip(),
                    'owners': [caller.owner_id, peer.owner_id],
                    'bindings': [caller.binding_id, peer.binding_id],
                    'approvals': [], 'state': 'pending',
                    'expires_at': min(self._clock() + 86400, window.start.timestamp()), 'event_id': None}
        self._store.create(proposal)
        return self._public(proposal)

    @staticmethod
    def _public(proposal):
        return {key: proposal[key] for key in ('id', 'start', 'end', 'summary', 'state', 'event_id', 'expires_at')}

    def _check(self, proposal):
        self._authorize(proposal['caller_id'], proposal['peer_id'], 'app.calendar:book')
        self._authorize(proposal['caller_id'], proposal['peer_id'], 'app.calendar:availability')
        self._authorize(proposal['caller_id'], proposal['peer_id'], 'app.calendar:propose')
        pair = self._pair(proposal['caller_id'], proposal['peer_id'])
        if ([b.owner_id for b in pair] != proposal['owners']
                or [b.binding_id for b in pair] != proposal['bindings']):
            raise SchedulingError('calendar binding changed; create a new proposal')
        if proposal['state'] != 'booked' and proposal['expires_at'] <= self._clock():
            raise SchedulingError('meeting proposal expired')
        return pair

    def approve(self, proposal_id: str, owner_id: str):
        """Trusted host API ONLY. The host must authenticate owner_id beforehand.

        This method is deliberately absent from agent tools and app operations.
        Approval is for this immutable proposal, not a general booking permission.
        """
        with self._store.locked(proposal_id) as proposal:
            self._check(proposal)
            if proposal['state'] != 'pending' or owner_id not in proposal['owners']:
                raise SchedulingError('owner cannot approve this proposal')
            if owner_id not in proposal['approvals']:
                proposal['approvals'].append(owner_id)
            return self._public(proposal)

    def reject(self, proposal_id: str, owner_id: str):
        """Trusted host API: decline a pending proposal; creates no calendar write."""
        with self._store.locked(proposal_id) as proposal:
            if proposal['state'] != 'pending' or owner_id not in proposal['owners']:
                raise SchedulingError('owner cannot reject this proposal')
            proposal['approvals'] = []
            proposal['state'] = 'rejected'
            return self._public(proposal)

    def status(self, caller_id: str, peer_id: str, proposal_id: str):
        self._authorize(caller_id, peer_id, 'app.calendar:propose')
        proposal = self._store.get(proposal_id)
        if (caller_id, peer_id) != (proposal['caller_id'], proposal['peer_id']):
            raise SchedulingError('proposal does not belong to this connection')
        return self._public(proposal)

    def book(self, caller_id: str, peer_id: str, proposal_id: str):
        # Commit intent before the provider write. A crash or timeout preserves
        # 'booking', allowing the same provider request ID to be reconciled.
        with self._store.locked(proposal_id) as proposal:
            if (caller_id, peer_id) != (proposal['caller_id'], proposal['peer_id']):
                raise SchedulingError('proposal does not belong to this connection')
            caller, peer = self._check(proposal)
            if proposal['state'] == 'booked':
                return self._public(proposal)
            if proposal['state'] not in ('pending', 'booking'):
                raise SchedulingError('meeting proposal cannot be booked')
            if set(proposal['approvals']) != set(proposal['owners']):
                raise SchedulingError('both owners must approve before booking')
            if proposal['state'] == 'pending':
                if self._store.conflicts(proposal):
                    raise SchedulingError('meeting conflicts with another booking or pending booking attempt')
                window = TimeWindow.parse(proposal['start'], proposal['end'])
                if any(not any(free.start <= window.start and free.end >= window.end
                               for free in self._free(binding, window)) for binding in (caller, peer)):
                    raise SchedulingError('meeting time is no longer available')
                proposal['state'] = 'booking'
        with self._store.locked(proposal_id) as proposal:
            caller, peer = self._check(proposal)
            if proposal['state'] == 'booked':
                return self._public(proposal)
            event = caller.provider.create_event(request_id=proposal['id'],
                window=TimeWindow.parse(proposal['start'], proposal['end']),
                summary=proposal['summary'], attendee=peer.attendee_address)
            proposal['event_id'] = event.event_id
            proposal['state'] = 'booked'
            return self._public(proposal)
