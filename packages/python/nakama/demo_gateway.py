"""Disposable local operator environment for SDK demonstrations."""
import http.cookiejar
from http.server import ThreadingHTTPServer
from pathlib import Path
import secrets
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from gateway import console, identity, sqlite_store
from gateway.apps import AppRegistry
from gateway.server import Ctx, Handler

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class DemoGateway:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nakama-demo-')
        self.store = sqlite_store.SQLiteStorage(str(Path(self.tmp.name) / 'gateway.db'))
        keys = identity.ensure_gateway_keys(self.store)
        self.token = secrets.token_urlsafe(32)
        self.store.set_config('console_token_hash', console._hash(self.token))
        self.registry = AppRegistry()
        self.console = console.ConsoleApp(self.store, keys)
        handler = type('DemoHandler', (Handler,), {
            'ctx': Ctx(self.store, keys, self.registry), 'console_app': self.console,
            'log_message': lambda *args: None})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = 'http://127.0.0.1:%d' % self.server.server_port
        self.operator = urllib.request.build_opener(_NoRedirect,
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.post('/console/login', {'token': self.token})
        return self

    def add_app(self, adapter):
        self.registry.register(adapter)
        self.console.scopes = tuple(dict.fromkeys((*self.console.scopes, *self.registry.scopes())))

    def post(self, path, fields):
        request = urllib.request.Request(self.base_url + path,
            data=urllib.parse.urlencode(fields, doseq=True).encode(),
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            with self.operator.open(request, timeout=10) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 303:
                raise
            exc.close()

    def approve_connection(self, request_id, scopes):
        self.post('/console/requests/%s/accept' % request_id, {'scope': scopes, 'days': '1'})

    def revoke_connection(self, request_id):
        self.post('/console/friendships/%s/unfriend' % request_id, {})

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store._db.close()
        self.tmp.cleanup()
