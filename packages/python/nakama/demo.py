"""Disposable local SDK demonstration; no vendor account or external API needed."""
import http.cookiejar
import json
import secrets
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

from gateway import console, identity, sqlite_store
from gateway.server import Ctx, Handler
from . import A2ATransport, Client, GatewayError, verify_envelope


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def run():
    """Approve a connection, exchange a verified message, then revoke access."""
    with tempfile.TemporaryDirectory(prefix='nakama-demo-') as tmp:
        store = sqlite_store.SQLiteStorage(str(Path(tmp) / 'gateway.db'))
        keys = identity.ensure_gateway_keys(store)
        token = secrets.token_urlsafe(32)
        store.set_config('console_token_hash', console._hash(token))
        handler = type('DemoHandler', (Handler,), {
            'ctx': Ctx(store, keys), 'console_app': console.ConsoleApp(store, keys),
            'log_message': lambda *args: None})
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:%d' % server.server_port
        operator = urllib.request.build_opener(_NoRedirect,
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def operator_post(path, fields):
            body = urllib.parse.urlencode(fields, doseq=True).encode()
            request = urllib.request.Request(base + path, data=body,
                headers={'Content-Type': 'application/x-www-form-urlencoded'})
            try:
                with operator.open(request, timeout=10) as response:
                    response.read()
            except urllib.error.HTTPError as exc:
                if exc.code != 303:
                    raise
                exc.close()

        def expect_denied():
            try:
                alice.send_message(bob.agent_id, {'text': 'coordinate'})
            except GatewayError as exc:
                if exc.code != 403:
                    raise
                print('Access denied:', exc.data['reason'])
            else:
                raise RuntimeError('expected access to be denied')

        try:
            alice = Client.new(base)
            bob = Client.new(base, transport=A2ATransport(base))
            alice.register('Alice', vendor='local-python')
            bob.register('Bob', vendor='local-python')
            expect_denied()
            request = alice.friend_request(to_agent_id=bob.agent_id)
            operator_post('/console/login', {'token': token})
            operator_post('/console/requests/%s/accept' % request,
                          {'scope': 'messages:send', 'days': '1'})
            print('Local demo operator approved messages:send')
            cursor = bob.inbox()['next_cursor']
            sent = alice.send_message(bob.agent_id, {'type': 'coordination.request', 'subject': 'meeting'})
            message = bob.inbox(after=cursor)['items'][0]['envelope']
            verify_envelope(message, alice.public_key_hex)
            print('Message queued and signature verified:', sent['message_id'])
            print('Recipient content:', json.dumps(message['payload']['content']))
            operator_post('/console/friendships/%s/unfriend' % request, {})
            expect_denied()
            print('Demo complete. Temporary identities and database removed.')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store._db.close()
