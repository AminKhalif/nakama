"""Malformed server responses and redirect behavior use a real HTTP endpoint."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nakama import ClientError, HTTPTransport


class TransportFailures(unittest.TestCase):
    def setUp(self):
        self.mode = 'mismatch'
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if test.mode == 'redirect':
                    self.send_response(307)
                    self.send_header('Location', '/forwarded')
                    self.end_headers()
                    return
                body = {'jsonrpc': '2.0', 'id': req['id'], 'result': {}}
                if test.mode == 'mismatch': body['id'] += 1
                if test.mode == 'missing': del body['result']
                if test.mode == 'both': body['error'] = {'code': 400, 'message': 'x'}
                if test.mode == 'invalid-error': body = {'jsonrpc': '2.0', 'id': req['id'], 'error': 'invalid'}
                raw = b'not json' if test.mode == 'invalid-json' else json.dumps(body).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.transport = HTTPTransport('http://127.0.0.1:%d' % self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_invalid_responses_fail_closed(self):
        for mode in ('mismatch', 'missing', 'both', 'invalid-error', 'invalid-json', 'redirect'):
            with self.subTest(mode=mode):
                self.mode = mode
                with self.assertRaises(ClientError):
                    self.transport.request('gw.inbox', {})

    def test_invalid_configuration_and_nonfinite_payload(self):
        for url in ('file:///tmp/x', 'http://user:password@example.com', 'http://example.com?token=x'):
            with self.assertRaises(ClientError): HTTPTransport(url)
        for timeout in (-1, 0, float('inf'), float('nan')):
            with self.assertRaises(ClientError): HTTPTransport('http://localhost', timeout)
        with self.assertRaises(ClientError): self.transport.request('x', {'value': float('nan')})
