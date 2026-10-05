"""Local SDK demonstrations; no vendor or calendar account required."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from . import A2ATransport, Client, GatewayError, verify_envelope
from .demo_gateway import DemoGateway


def expect_denied(call):
    try:
        call()
    except GatewayError as exc:
        if exc.code not in (403, 409):
            raise
        print('Access denied:', exc.data['reason'])
    else:
        raise RuntimeError('expected access to be denied')


def run():
    with DemoGateway() as demo:
        alice = Client.new(demo.base_url)
        bob = Client.new(demo.base_url, transport=A2ATransport(demo.base_url))
        alice.register('Alice', vendor='local-python')
        bob.register('Bob', vendor='local-python')
        expect_denied(lambda: alice.send_message(bob.agent_id, {'text': 'coordinate'}))
        request = alice.friend_request(to_agent_id=bob.agent_id)
        demo.approve_connection(request, ['messages:send'])
        print('Local demo operator approved messages:send')
        cursor = bob.inbox()['next_cursor']
        sent = alice.send_message(bob.agent_id, {'type': 'coordination.request', 'subject': 'meeting'})
        message = bob.inbox(after=cursor)['items'][0]['envelope']
        verify_envelope(message, alice.public_key_hex)
        print('Message queued and signature verified:', sent['message_id'])
        print('Recipient content:', json.dumps(message['payload']['content']))
        demo.revoke_connection(request)
        expect_denied(lambda: alice.send_message(bob.agent_id, {}))
    print('Demo complete. Temporary identities and database removed.')


def run_scheduling():
    from gateway.apps import require_peer_scope
    from .scheduling import (CalendarBinding, MeetingService, MemoryCalendar,
                             SchedulingClient, SQLiteProposalStore, TimeWindow)
    from .scheduling.adapter import CalendarAdapter
    with DemoGateway() as demo:
        alice = Client.new(demo.base_url)
        bob = Client.new(demo.base_url, transport=A2ATransport(demo.base_url))
        alice.register('Alice', vendor='local-python')
        bob.register('Bob', vendor='local-python')
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 14, tzinfo=timezone.utc)
        query = TimeWindow(start, start + timedelta(hours=3))
        left = MemoryCalendar([TimeWindow(start, start + timedelta(hours=1))])
        right = MemoryCalendar([TimeWindow(start + timedelta(minutes=90), start + timedelta(hours=2))])
        proposals = SQLiteProposalStore(str(Path(demo.tmp.name) / 'meetings.db'))
        try:
            service = MeetingService({
                alice.agent_id: CalendarBinding('owner-alice', left, 'alice@example.invalid', (query,), 'alice-calendar-v1'),
                bob.agent_id: CalendarBinding('owner-bob', right, 'bob@example.invalid', (query,), 'bob-calendar-v1')},
                proposals, lambda caller, peer, scope: require_peer_scope(demo.store, caller, peer, scope))
            demo.add_app(CalendarAdapter(service))
            scheduling = SchedulingClient(alice)
            bounds = {'start': query.start.astimezone(timezone(timedelta(hours=-4))).isoformat(),
                      'end': query.end.astimezone(timezone(timedelta(hours=1))).isoformat()}
            expect_denied(lambda: scheduling.find_slots(bob.agent_id, **bounds))
            request = alice.friend_request(to_agent_id=bob.agent_id)
            demo.approve_connection(request, ['app.calendar:availability', 'app.calendar:propose', 'app.calendar:book'])
            slots = scheduling.find_slots(bob.agent_id, **bounds, duration_minutes=30)['slots']
            print('Shared slots (UTC, no event details):', json.dumps(slots))
            meeting = scheduling.propose(bob.agent_id, **slots[0], summary='Project meeting')
            expect_denied(lambda: scheduling.book(bob.agent_id, meeting['id']))
            # Trusted host API; the local demo simulates both authenticated owners.
            service.approve(meeting['id'], 'owner-alice')
            expect_denied(lambda: scheduling.book(bob.agent_id, meeting['id']))
            service.approve(meeting['id'], 'owner-bob')
            print('Both demo owners approved the exact proposal')
            result = scheduling.book(bob.agent_id, meeting['id'])
            if scheduling.book(bob.agent_id, meeting['id']) != result or len(left.events) != 1:
                raise RuntimeError('booking must be idempotent')
            print('One organizer event booked; no duplicate:', result['event_id'])
            demo.revoke_connection(request)
            expect_denied(lambda: scheduling.availability(bob.agent_id, **bounds))
        finally:
            proposals.close()
    print('Scheduling demo complete. Local calendars only; no external invitations sent.')
