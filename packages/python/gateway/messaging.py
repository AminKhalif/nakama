"""Recipient-private inbox and scoped peer messaging."""
from . import apps, wire

MESSAGE_SCOPE = 'messages:send'


def friends_list(store, caller_id):
    entries = []
    for fr in store.list_friendships():
        if caller_id not in (fr['a_id'], fr['b_id']):
            continue
        peer_id = fr['b_id'] if caller_id == fr['a_id'] else fr['a_id']
        peer = store.get_agent(peer_id)
        entries.append({'friendship_id': fr['id'], 'status': fr['status'],
                        'peer_id': peer_id, 'name': peer['name'], 'vendor': peer['vendor'],
                        'identity_document': peer['identity_doc'],
                        'grants': [g for g in store.grants_for_friendship(fr['id'])
                                   if g['agent_id'] == caller_id]})
    return {'friends': entries}


def send(store, caller_id, envelope):
    payload = envelope['payload']
    peer_id, content = payload.get('peer_id'), payload.get('content')
    if not isinstance(content, dict):
        raise wire.AppError('bad_request', 'content must be a JSON object')
    apps.require_peer_scope(store, caller_id, peer_id, MESSAGE_SCOPE)
    # Retain the sender's original signature, rather than re-signing their content.
    store.push_envelope(peer_id, None, 'gw.message_send', envelope)
    store.log_event('message.sent', 'Peer message queued', agent_id=caller_id)
    return {'message_id': envelope['msg_id'], 'status': 'queued'}


def inbox(store, caller_id, payload):
    after, limit = payload.get('after', 0), payload.get('limit', 50)
    if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise wire.AppError('bad_request', 'after must be nonnegative; limit must be 1..100')
    rows = store.inbox_after(caller_id, after, limit)
    return {'items': rows, 'next_cursor': rows[-1]['id'] if rows else after}
