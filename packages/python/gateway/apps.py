"""Application extension point; the gateway authorizes before calling an adapter."""
import re
from typing import Mapping

from nakama.contracts import AppAdapter, AppContext, Operation

from . import friends, wire

_NAME = re.compile(r'^[a-z][a-z0-9_.-]{0,63}$')
_SCOPE = re.compile(r'^[a-z][a-z0-9_.-]*:[a-z][a-z0-9_.-]*$')


class AppRegistry:
    def __init__(self, adapters=()):
        self._operations = {}
        self._apps = set()
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: AppAdapter):
        if not _NAME.fullmatch(adapter.app_id) or adapter.app_id in self._apps:
            raise ValueError('invalid or duplicate application id')
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:
            raise RuntimeError('install nakama-interop[apps] to register application adapters') from exc
        operations = tuple(adapter.operations())
        names = set()
        for op in operations:
            if (not _NAME.fullmatch(op.name) or op.name in names
                    or not _SCOPE.fullmatch(op.scope)
                    or not op.scope.startswith('app.' + adapter.app_id + ':')
                    or not callable(op.handler) or not isinstance(op.input_schema, Mapping)):
                raise ValueError('invalid or duplicate operation declaration')
            Draft202012Validator.check_schema(dict(op.input_schema))
            names.add(op.name)
        self._apps.add(adapter.app_id)
        for op in operations:
            self._operations[(adapter.app_id, op.name)] = op

    def scopes(self):
        return tuple(sorted({op.scope for op in self._operations.values()}))

    def describe(self):
        return [{'app': app, 'operation': name, 'scope': op.scope,
                 'description': op.description, 'input_schema': dict(op.input_schema)}
                for (app, name), op in sorted(self._operations.items())]

    def invoke(self, store, caller_id, payload):
        app, operation = payload.get('app'), payload.get('operation')
        if not isinstance(app, str) or not isinstance(operation, str):
            raise wire.AppError('bad_request', 'app and operation must be strings')
        op = self._operations.get((app, operation))
        if op is None:
            raise wire.AppError('not_found', 'unknown application operation', 404)
        data = payload.get('input', {})
        if not isinstance(data, dict):
            raise wire.AppError('bad_request', 'input must be an object')
        peer = payload.get('peer_id')
        fr = require_peer_scope(store, caller_id, peer, op.scope)
        from jsonschema import Draft202012Validator, ValidationError
        try:
            Draft202012Validator(dict(op.input_schema)).validate(data)
        except ValidationError:
            raise wire.AppError('bad_request', 'input does not match the operation schema')
        # Adapters enforce account-level ACLs beyond the directional grant.
        # The context is gateway-issued, never taken from the submitted input.
        result = op.handler(AppContext(caller_id, peer, fr['id']), data)
        store.log_event('app.invoked', '%s.%s' % (app, operation), agent_id=caller_id)
        return {'app': app, 'operation': operation, 'result': result}


def require_peer_scope(store, caller_id, peer_id, scope):
    if not isinstance(peer_id, str) or not peer_id or peer_id == caller_id:
        raise wire.AppError('bad_request', 'peer_id must identify another agent')
    peer = store.get_agent(peer_id)
    if not peer:
        raise wire.AppError('not_found', 'unknown peer', 404)
    from . import identity
    if store.is_revoked(peer['pubkey']) or identity.doc_expired(peer['identity_doc']):
        raise wire.AppError('revoked', 'peer identity is revoked or expired', 403)
    fr = store.get_friendship_between(caller_id, peer_id)
    if not fr or fr['status'] != 'accepted':
        raise wire.AppError('not_friends', 'accepted friendship required', 403)
    active, _grant = friends.grant_active(store, fr['id'], caller_id, scope)
    if not active:
        raise wire.AppError('scope_required', 'active grant required: ' + scope, 403)
    return fr
