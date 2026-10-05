"""Real HTTP tests for SDK, console permissions, messaging, and applications."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'examples' / 'budget'))
from gwtest_harness import Console
from nakama import A2ATransport, Client, ClientError, GatewayError, verify_envelope
from nakama.apps import AppRegistry
from nakama.connectors import GatewayConnector, get_profile
from nakama.credentials import load_client, register_agent
from gateway import console, identity, sqlite_store
from gateway.server import Ctx, Handler
from adapter import BudgetAdapter


class ExtensionsLive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = sqlite_store.SQLiteStorage(str(Path(self.tmp.name) / 'gw.db'))
        keys = identity.ensure_gateway_keys(self.store)
        self.store.set_config('console_token_hash', console._hash('test-operator'))
        self.budget = BudgetAdapter({})
        registry = AppRegistry([self.budget])
        context = Ctx(self.store, keys, registry)
        # Per-server handler avoids mutating global Handler state in embedded use.
        handler = type('TestHandler', (Handler,), {
            'ctx': context, 'console_app': console.ConsoleApp(self.store, keys, scopes=registry.scopes()),
            'log_message': lambda *args: None})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:%d' % self.server.server_port
        self.operator = Console(self.base, 'test-operator')
        self.a = Client.new(self.base)
        self.a.register('Alice')
        self.b = Client.new(self.base, transport=A2ATransport(self.base))
        self.b.register('Bob', vendor='hermes')
        self.c = Client.new(self.base)
        self.c.register('Charlie')
        self.budget._accounts[self.b.agent_id] = {'currency': 'USD', 'monthly_limit': 1200}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store._db.close()
        self.tmp.cleanup()

    def accept(self, scopes):
        request = self.a.friend_request(to_agent_id=self.b.agent_id)
        # Lists are encoded with doseq using the real console HTTP surface.
        from urllib.parse import urlencode
        body = urlencode({'scope': scopes, 'days': '1'}, doseq=True).encode()
        status, _, _ = self.operator._http('POST', '/console/requests/%s/accept' % request,
            body=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(status, 303)
        return request

    def denied(self, call, name):
        with self.assertRaises(GatewayError) as caught:
            call()
        self.assertIn(name, str(caught.exception))

    def test_empty_scope_sheet_grants_nothing(self):
        friendship = self.accept([])
        self.assertEqual(self.store.grants_for_friendship(friendship), [])
        self.denied(lambda: self.a.send_message(self.b.agent_id, {'text': 'hello'}), 'scope_required')
        self.denied(lambda: self.a.invoke_app('budget', 'summary', self.b.agent_id), 'scope_required')

    def test_messaging_roundtrip_signatures_private_cursor_and_replay(self):
        self.denied(lambda: self.a.send_message(self.b.agent_id, {}), 'not_friends')
        self.accept(['messages:send'])
        cursor = self.b.inbox()['next_cursor']
        result = self.a.send_message(self.b.agent_id, {'text': 'hello'})
        page = self.b.inbox(after=cursor, limit=1)
        self.assertEqual(len(page['items']), 1)
        env = page['items'][0]['envelope']
        self.assertEqual(env['payload']['content'], {'text': 'hello'})
        self.assertEqual(result['message_id'], env['msg_id'])
        self.assertTrue(verify_envelope(env, self.a.public_key_hex))
        self.assertEqual(self.b.inbox(after=page['next_cursor'])['items'], [])
        self.assertEqual(self.a.inbox(after=cursor)['items'], [])
        self.assertEqual(self.c.inbox()['items'], [])
        self.denied(lambda: self.a._rpc('gw.message_send', env), 'duplicate')
        self.b.send_message(self.a.agent_id, {'ack': True})  # A2A transport write
        self.assertEqual(self.a.inbox(after=cursor)['items'][0]['envelope']['payload']['content'], {'ack': True})
        self.denied(lambda: self.a.inbox(after=True), 'bad_request')
        self.denied(lambda: self.a.send_message(self.b.agent_id, 'invalid'), 'bad_request')
        self.denied(lambda: self.a.send_message(['invalid'], {}), 'bad_request')

    def test_scoped_app_context_schema_and_revocation(self):
        fr = self.accept(['app.budget:read'])
        self.assertEqual(self.a.applications()[0]['scope'], 'app.budget:read')
        result = self.a.invoke_app('budget', 'summary', self.b.agent_id)
        self.assertEqual(result['result']['monthly_limit'], 1200)
        self.denied(lambda: self.a.invoke_app('budget', 'summary', self.b.agent_id,
                                             {'peer_id': self.c.agent_id}), 'bad_request')
        self.denied(lambda: self.a.invoke_app('budget', 'summary', self.c.agent_id), 'not_friends')
        self.denied(lambda: self.a.invoke_app('budget', 'unknown', self.b.agent_id), 'not_found')
        self.denied(lambda: self.a.send_message(self.b.agent_id, {}), 'scope_required')
        self.operator.action('/console/friendships/%s/unfriend' % fr)
        self.denied(lambda: self.a.invoke_app('budget', 'summary', self.b.agent_id), 'not_friends')

    def test_expired_and_directional_grants(self):
        fr = self.accept(['messages:send', 'app.budget:read'])
        for grant in self.store.grants_for_friendship(fr):
            if grant['agent_id'] == self.a.agent_id:
                self.store.set_grant_expiry(grant['id'], time.time() - 1)
        self.denied(lambda: self.a.send_message(self.b.agent_id, {}), 'scope_required')
        self.denied(lambda: self.a.invoke_app('budget', 'summary', self.b.agent_id), 'scope_required')
        self.b.send_message(self.a.agent_id, {'direction': 'b-to-a'})

    def test_peer_key_revocation_and_agent_cannot_approve(self):
        self.accept(['messages:send', 'app.budget:read'])
        self.operator.action('/console/keys/revoke', {'pubkey': 'ed25519:' + self.b.public_key_hex, 'reason': 'test'})
        self.denied(lambda: self.a.send_message(self.b.agent_id, {}), 'revoked')
        self.denied(lambda: self.a.invoke_app('budget', 'summary', self.b.agent_id), 'revoked')
        self.denied(lambda: self.b.inbox(), 'revoked')
        self.denied(lambda: self.a.friend_decide('fr_invalid', 'accept'), 'console_only')

    def test_connector_uses_shared_contract(self):
        self.accept(['messages:send'])
        connector = GatewayConnector(self.a)
        self.assertEqual(connector.call('friends', {})[0]['peer_id'], self.b.agent_id)
        self.assertEqual(connector.call('send_message', {'peer_id': self.b.agent_id, 'content': {}})['status'], 'queued')
        for name, arguments in [('friend_decide', {}), ('inbox', {'limit': 101}),
                                ('send_message', {'peer_id': self.b.agent_id}), ('friends', {'private_key': 'x'})]:
            with self.assertRaises(ValueError):
                connector.call(name, arguments)
        config = get_profile('hermes').stdio_config(python=sys.executable, credentials='/tmp/local-identity.json')
        self.assertIn('mcp_servers', config)
        with self.assertRaises(ValueError):
            get_profile('instinct').stdio_config(python=sys.executable, credentials='x')

    def test_mcp_stdio_tools_call_live_gateway(self):
        import asyncio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        path = Path(self.tmp.name) / 'credentials-mcp.json'
        local = register_agent(path, self.base, 'MCPAgent', vendor='hermes')
        self.operator.action('/console/invite/%s/mint' % self.b.agent_id)
        code = self.store.active_invite_code(self.b.agent_id)['code']

        async def exercise():
            params = StdioServerParameters(command=sys.executable,
                args=['-m', 'nakama', 'mcp', '--credentials', str(path)])
            with open(Path(self.tmp.name) / 'mcp-stderr.log', 'w') as errlog:
                async with stdio_client(params, errlog=errlog) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertEqual({t.name for t in tools.tools},
                            {'friends', 'request_friendship', 'send_message', 'inbox', 'applications', 'invoke_app'})
                        self.assertTrue(next(t for t in tools.tools if t.name == 'inbox').annotations.readOnlyHint)
                        self.assertFalse(next(t for t in tools.tools if t.name == 'send_message').annotations.readOnlyHint)
                        request = await session.call_tool('request_friendship', {'invite_code': code})
                        self.assertFalse(request.isError)
                        request_id = json.loads(request.content[0].text)['request_id']
                        blocked = await session.call_tool('send_message',
                            {'peer_id': self.b.agent_id, 'content': {'via': 'mcp'}})
                        self.assertTrue(blocked.isError)
                        self.operator.action('/console/requests/%s/accept' % request_id,
                                             {'scope': 'messages:send', 'days': '1'})
                        sent = await session.call_tool('send_message',
                            {'peer_id': self.b.agent_id, 'content': {'via': 'mcp'}})
                        self.assertFalse(sent.isError)
                        applications = await session.call_tool('applications', {})
                        self.assertFalse(applications.isError)
                        self.assertEqual(json.loads(applications.content[0].text)['operations'][0]['app'], 'budget')
                        denied = await session.call_tool('invoke_app',
                            {'app': 'budget', 'operation': 'summary', 'peer_id': self.b.agent_id, 'data': {}})
                        self.assertTrue(denied.isError)
        asyncio.run(exercise())
        messages = [item['envelope'] for item in self.b.inbox()['items']
                    if item['envelope']['type'] == 'gw.message_send']
        self.assertEqual(messages[-1]['payload']['content'], {'via': 'mcp'})
        self.assertEqual(messages[-1]['from'], local.agent_id)

    def test_credentials_roundtrip_and_file_permissions(self):
        path = Path(self.tmp.name) / 'credentials.json'
        client = register_agent(path, self.base, 'Local')
        self.assertEqual(load_client(path).agent_id, client.agent_id)
        self.assertEqual(load_client(path).friends(), [])
        with self.assertRaises(FileExistsError):
            register_agent(path, self.base, 'Overwrite')
        if os.name == 'posix':
            path.chmod(0o644)
            with self.assertRaises(ClientError):
                load_client(path)


if __name__ == '__main__':
    unittest.main()
