"""Scheduling privacy, authorization, owner approval, and booking recovery."""
from datetime import timedelta
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from gateway.apps import require_peer_scope
from nakama import A2ATransport, Client, GatewayError
from nakama.demo_gateway import DemoGateway
from nakama.scheduling import (CalendarBinding, GoogleCalendar, MeetingService,
    MemoryCalendar, SchedulingClient, SchedulingError, SQLiteProposalStore,
    TimeWindow, available, shared_slots)
from nakama.scheduling.adapter import CalendarAdapter

QUERY = TimeWindow.parse('2030-01-02T10:00:00Z', '2030-01-02T13:00:00Z')
NOW = QUERY.start.timestamp() - 3600
SCOPES = ('app.calendar:availability', 'app.calendar:propose', 'app.calendar:book')


def bindings(left, right, query=QUERY):
    return {'alice': CalendarBinding('owner-a', left, 'a@example.invalid', (query,), 'account-a'),
            'bob': CalendarBinding('owner-b', right, 'b@example.invalid', (query,), 'account-b')}


class Windows(unittest.TestCase):
    def test_timezones_clipping_and_adjacent_busy(self):
        query = TimeWindow.parse('2030-01-02T05:00:00-05:00', '2030-01-02T14:00:00+01:00')
        self.assertEqual(query, QUERY)
        busy = [TimeWindow.parse('2030-01-02T09:00:00Z', '2030-01-02T11:00:00Z'),
                TimeWindow.parse('2030-01-02T11:00:00Z', '2030-01-02T12:00:00Z')]
        self.assertEqual(available(query, (query,), busy),
                         (TimeWindow.parse('2030-01-02T12:00:00Z', '2030-01-02T13:00:00Z'),))
        self.assertEqual(available(query, (), ()), ())

    def test_invalid_times_and_duration(self):
        for start, end in [('2030-01-02T10:00:00', '2030-01-02T11:00:00Z'),
                           ('bad', 'bad'), ('2030-01-02T11:00:00Z', '2030-01-02T10:00:00Z')]:
            with self.assertRaises(SchedulingError):
                TimeWindow.parse(start, end)
        for duration in (True, 0, 481):
            with self.assertRaises(SchedulingError):
                shared_slots((QUERY,), (QUERY,), duration)


class Scheduling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'proposals.db')
        self.store = SQLiteProposalStore(self.path)
        self.left, self.right = MemoryCalendar(), MemoryCalendar()
        self.scopes = set(SCOPES)
        self.now = NOW
        self.service = self.make_service()

    def make_service(self, links=None):
        def authorize(caller, peer, scope):
            if (caller, peer) != ('alice', 'bob') or scope not in self.scopes:
                raise SchedulingError('permission denied')
        return MeetingService(links or bindings(self.left, self.right), self.store,
                              authorize, clock=lambda: self.now)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def propose(self):
        return self.service.propose('alice', 'bob',
            TimeWindow(QUERY.start, QUERY.start + timedelta(minutes=30)), 'Planning')

    def approve(self, proposal):
        for owner in ('owner-a', 'owner-b'):
            self.service.approve(proposal['id'], owner)

    def test_free_time_only_and_explicit_sharing(self):
        result = self.service.availability('alice', 'bob', QUERY)
        self.assertEqual(result, {'windows': [QUERY.as_dict()]})
        self.assertNotIn('example.invalid', str(result))
        self.assertNotIn('owner', str(result))
        links = bindings(self.left, self.right)
        links['bob'] = CalendarBinding('owner-b', self.right, 'b@example.invalid', (), 'account-b')
        self.assertEqual(self.make_service(links).availability('alice', 'bob', QUERY), {'windows': []})

    def test_both_owners_exact_proposal_and_separate_scope(self):
        first, second = self.propose(), self.propose()
        self.service.approve(first['id'], 'owner-a')
        with self.assertRaises(SchedulingError):
            self.service.book('alice', 'bob', first['id'])
        with self.assertRaises(SchedulingError):
            self.service.approve(first['id'], 'unrelated-owner')
        self.service.approve(first['id'], 'owner-b')
        with self.assertRaises(SchedulingError):
            self.service.book('alice', 'bob', second['id'])
        self.scopes.remove('app.calendar:book')
        with self.assertRaises(SchedulingError):
            self.service.book('alice', 'bob', first['id'])
        self.assertEqual(self.left.events, {})

    def test_booking_rechecks_availability(self):
        proposal = self.propose()
        self.approve(proposal)
        self.right.create_event(request_id='unrelated', window=QUERY, summary='Private', attendee='private')
        with self.assertRaisesRegex(SchedulingError, 'no longer available'):
            self.service.book('alice', 'bob', proposal['id'])
        self.assertEqual(self.left.events, {})

    def test_owner_rejection_prevents_booking(self):
        proposal = self.propose()
        self.approve(proposal)
        self.assertEqual(self.service.reject(proposal['id'], 'owner-b')['state'], 'rejected')
        with self.assertRaises(SchedulingError):
            self.service.book('alice', 'bob', proposal['id'])
        with self.assertRaises(SchedulingError):
            self.service.approve(proposal['id'], 'owner-a')
        self.assertEqual(self.left.events, {})

    def test_idempotency_restart_and_scope_revocation(self):
        proposal = self.propose()
        self.approve(proposal)
        result = self.service.book('alice', 'bob', proposal['id'])
        self.store.close()
        self.store = SQLiteProposalStore(self.path)
        self.service = self.make_service()
        self.assertEqual(self.service.book('alice', 'bob', proposal['id']), result)
        self.assertEqual(len(self.left.events), 1)
        self.scopes.clear()
        with self.assertRaises(SchedulingError):
            self.service.book('alice', 'bob', proposal['id'])

    def test_expiry_binding_change_and_query_bound(self):
        proposal = self.propose()
        self.approve(proposal)
        links = bindings(self.left, self.right)
        links['bob'] = CalendarBinding('owner-b', self.right, 'new@example.invalid', (QUERY,), 'changed-account')
        with self.assertRaisesRegex(SchedulingError, 'binding changed'):
            self.make_service(links).book('alice', 'bob', proposal['id'])
        self.now = proposal['expires_at']
        with self.assertRaisesRegex(SchedulingError, 'expired'):
            self.service.book('alice', 'bob', proposal['id'])
        self.now = NOW
        with self.assertRaises(SchedulingError):
            self.service.find_slots('alice', 'bob', TimeWindow(QUERY.start, QUERY.start + timedelta(days=32)))
        with self.assertRaises(SchedulingError):
            self.service.status('bob', 'alice', proposal['id'])

    def test_timeout_recovery_reserves_slot(self):
        class TimeoutAfterWrite(MemoryCalendar):
            first = True
            def create_event(self, **kwargs):
                event = super().create_event(**kwargs)
                if self.first:
                    self.first = False
                    raise SchedulingError('provider timed out after write')
                return event
        self.left = TimeoutAfterWrite()
        self.service = self.make_service()
        first, second = self.propose(), self.propose()
        self.approve(first)
        self.approve(second)
        with self.assertRaisesRegex(SchedulingError, 'timed out'):
            self.service.book('alice', 'bob', first['id'])
        self.assertEqual(self.store.get(first['id'])['state'], 'booking')
        with self.assertRaisesRegex(SchedulingError, 'conflicts'):
            self.service.book('alice', 'bob', second['id'])
        self.store.close()
        self.store = SQLiteProposalStore(self.path)
        self.service = self.make_service()
        self.assertEqual(self.service.book('alice', 'bob', first['id'])['state'], 'booked')
        self.assertEqual(len(self.left.events), 1)


class GoogleProvider(unittest.TestCase):
    def test_freebusy_contract_and_failure_closed(self):
        class Fake:
            response = {'calendars': {'private-id': {'busy': [QUERY.as_dict()]}}}
            def freebusy(self): return self
            def query(self, **kwargs): self.request = kwargs; return self
            def execute(self): return self.response
        fake = Fake()
        calendar = GoogleCalendar(fake, 'private-id')
        self.assertEqual(calendar.busy(QUERY), (QUERY,))
        self.assertEqual(fake.request['body']['items'], [{'id': 'private-id'}])
        fake.response = {'calendars': {'private-id': {'errors': [{'reason': 'notFound'}], 'busy': []}}}
        with self.assertRaises(SchedulingError): calendar.busy(QUERY)
        with self.assertRaises(SchedulingError):
            calendar.create_event(request_id='x', window=QUERY, summary='Meeting', attendee='b@example.invalid')

    def test_google_insert_and_duplicate_reconciliation(self):
        class Conflict(Exception):
            resp = SimpleNamespace(status=409)
        class Fake:
            record = None
            mode = None
            def events(self): return self
            def insert(self, **kwargs): self.args = kwargs; self.mode = 'insert'; return self
            def get(self, **kwargs): self.mode = 'get'; return self
            def execute(self):
                if self.mode == 'insert':
                    if self.record is not None: raise Conflict()
                    self.record = dict(self.args['body'])
                return self.record
        fake = Fake()
        calendar = GoogleCalendar(None, write_service=fake)
        kwargs = dict(request_id='proposal-1', window=QUERY, summary='Meeting', attendee='b@example.invalid')
        first = calendar.create_event(**kwargs)
        self.assertEqual(first, calendar.create_event(**kwargs))
        self.assertEqual(first.event_id, hashlib.sha256(b'proposal-1').hexdigest())
        self.assertEqual(fake.args['sendUpdates'], 'all')
        fake.record['summary'] = 'changed'
        with self.assertRaises(SchedulingError): calendar.create_event(**kwargs)


class SchedulingLive(unittest.TestCase):
    def setUp(self):
        self.demo = DemoGateway().__enter__()
        self.a = Client.new(self.demo.base_url)
        self.b = Client.new(self.demo.base_url, transport=A2ATransport(self.demo.base_url))
        self.a.register('Alice')
        self.b.register('Bob')
        self.left, self.right = MemoryCalendar(), MemoryCalendar()
        self.proposals = SQLiteProposalStore(str(Path(self.demo.tmp.name) / 'meetings.db'))
        links = bindings(self.left, self.right)
        links = {self.a.agent_id: links['alice'], self.b.agent_id: links['bob']}
        self.service = MeetingService(links, self.proposals,
            lambda caller, peer, scope: require_peer_scope(self.demo.store, caller, peer, scope), clock=lambda: NOW)
        self.adapter = CalendarAdapter(self.service)
        self.demo.add_app(self.adapter)
        self.client = self.a.scheduling

    def tearDown(self):
        self.proposals.close()
        self.demo.__exit__()

    def test_signed_app_flow_privacy_approval_and_revocation(self):
        with self.assertRaises(GatewayError):
            self.client.availability(self.b.agent_id, **QUERY.as_dict())
        request = self.a.friend_request(to_agent_id=self.b.agent_id)
        self.demo.approve_connection(request, SCOPES)
        slots = self.client.find_slots(self.b.agent_id, **QUERY.as_dict())['slots']
        proposal = self.client.propose(self.b.agent_id, **slots[0], summary='Planning')
        with self.assertRaises(GatewayError): self.client.book(self.b.agent_id, proposal['id'])
        for owner in ('owner-a', 'owner-b'): self.service.approve(proposal['id'], owner)
        self.assertEqual(self.client.book(self.b.agent_id, proposal['id'])['state'], 'booked')
        self.assertEqual(len(self.left.events), 1)
        self.assertNotIn('approve', [op.name for op in self.adapter.operations()])
        with self.assertRaises(GatewayError):
            self.a.invoke_app('calendar', 'availability', self.b.agent_id,
                              {**QUERY.as_dict(), 'calendar_id': 'someone-else'})
        self.demo.revoke_connection(request)
        with self.assertRaises(GatewayError):
            self.client.availability(self.b.agent_id, **QUERY.as_dict())

    def test_availability_grant_cannot_create_proposal(self):
        request = self.a.friend_request(to_agent_id=self.b.agent_id)
        self.demo.approve_connection(request, ['app.calendar:availability'])
        self.assertTrue(self.client.find_slots(self.b.agent_id, **QUERY.as_dict())['slots'])
        with self.assertRaises(GatewayError):
            self.client.propose(self.b.agent_id, **QUERY.as_dict(), summary='Meeting')
        html = self.demo.console
        self.assertIn('app.calendar:book', html.scopes)
