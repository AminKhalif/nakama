"""Injectable JSON-RPC transport. Mutating requests are never retried."""
import json
import math
import threading
import urllib.error
import urllib.request
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

from .errors import ClientError, GatewayError

MAX_RESPONSE = 4 * 1024 * 1024


class Transport(Protocol):
    def request(self, method: str, params: Mapping[str, Any]) -> Any: ...
    def get_json(self, path: str) -> Any: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward signed payloads to an unconfigured endpoint.
        return None


class HTTPTransport:
    def __init__(self, base_url: str, timeout: float = 10):
        parsed = urlparse(base_url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ClientError('base_url must be an HTTP(S) URL without credentials, query, or fragment')
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ClientError('timeout must be a finite positive number')
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._counter = 0
        self._lock = threading.Lock()
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _read(self, response):
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ClientError('gateway response exceeds size limit')
        try:
            return json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeError) as exc:
            raise ClientError('gateway returned invalid JSON') from exc

    def _exchange(self, request):
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return self._read(response)
        except urllib.error.HTTPError as exc:
            try:
                reply = self._read(exc)
            except ClientError:
                raise ClientError('gateway returned HTTP %s' % exc.code) from exc
            if isinstance(reply, dict) and isinstance(reply.get('error'), dict):
                return reply
            raise ClientError('gateway returned HTTP %s' % exc.code) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ClientError('gateway transport failed') from exc

    def request(self, method, params):
        with self._lock:
            self._counter += 1
            request_id = self._counter
        try:
            body = json.dumps({'jsonrpc': '2.0', 'id': request_id,
                               'method': method, 'params': params}, allow_nan=False).encode()
        except (TypeError, ValueError) as exc:
            raise ClientError('request must contain JSON-compatible values') from exc
        reply = self._exchange(urllib.request.Request(
            self.base_url + '/rpc', data=body, method='POST',
            headers={'Content-Type': 'application/json', 'User-Agent': 'nakama-python/0.3'}))
        if (not isinstance(reply, dict) or reply.get('jsonrpc') != '2.0'
                or type(reply.get('id')) is not int or reply['id'] != request_id
                or ('result' in reply) == ('error' in reply)):
            raise ClientError('invalid or mismatched JSON-RPC response')
        if 'error' in reply:
            err = reply['error']
            if not isinstance(err, dict) or not isinstance(err.get('code'), int) or not isinstance(err.get('message'), str):
                raise ClientError('malformed JSON-RPC error')
            raise GatewayError(err['code'], err['message'], err.get('data'))
        return reply['result']

    def get_json(self, path):
        if not path.startswith('/') or path.startswith('//'):
            raise ClientError('discovery path must be relative to the gateway')
        return self._exchange(urllib.request.Request(
            self.base_url + path, headers={'User-Agent': 'nakama-python/0.3'}))


class A2ATransport(HTTPTransport):
    """Nakama's A2A message/send wrapper, not a general A2A task client."""
    def request(self, method, params):
        import uuid
        message = {'message': {'role': 'user', 'messageId': uuid.uuid4().hex,
                               'parts': [{'kind': 'text', 'text': json.dumps(params, allow_nan=False)}]}}
        result = super().request('message/send', message)
        try:
            reply = result['message']['parts'][0]
            if reply['kind'] != 'text':
                raise ValueError('expected text part')
            return json.loads(reply['text'])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ClientError('invalid Nakama A2A wrapper response') from exc
