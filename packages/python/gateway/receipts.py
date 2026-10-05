"""Hash-chained audit receipts (spec/receipts.md).

Each round produces a receipt recording both commitments, both revealed
cells, the resulting board, and the outcome. The gateway signs it; the
session's auditor independently verifies and countersigns via
gw.countersign; only then is the receipt published and the next round
opened. A final game receipt closes the chain. Each receipt's prev_hash is
the SHA-256 of the previous receipt's canonical bytes as published
(including both signatures); round 1 uses the "0"*64 genesis marker.

Secrets are verify-then-discard: reveals carry {cell} only, never secrets.
Anyone holding the gateway and auditor public keys can verify the whole
chain offline with the receipts.md §3 algorithm.
"""

import hashlib
import time

from . import crypto, wire


def signing_bytes(body):
    """Canonical bytes the signatures cover: everything except the two
    signature fields."""
    return wire.canonical_bytes({k: v for k, v in body.items()
                                 if k not in ("gw_sig", "auditor_sig")})


def published_hash(body):
    """SHA-256 hex of the canonical bytes of a receipt as published
    (signature fields included). This is what prev_hash commits to."""
    return hashlib.sha256(wire.canonical_bytes(body)).hexdigest()


def _prev_hash(store, session_id):
    published = store.published_receipts(session_id)
    if not published:
        return "0" * 64
    return published_hash(published[-1])


def emit_round_receipt(store, gw_keys, session_id, round_n, board_after,
                       result, game_over, forfeit, reason):
    """Build, gateway-sign, and store (unpublished) a round receipt."""
    gw_priv, _gw_pub = gw_keys
    s = store.get_session(session_id)
    rnd = store.get_round(session_id, round_n)
    body = {
        "session": session_id,
        "round": round_n,
        "commitments": {"a": rnd["commit_a"], "b": rnd["commit_b"]},
        "reveals": {
            "a": {"cell": rnd["cell_a"]} if rnd["cell_a"] else None,
            "b": {"cell": rnd["cell_b"]} if rnd["cell_b"] else None,
        },
        "board_after": list(board_after),
        "result": result,
        "game_over": game_over,
        "forfeit": forfeit,
        "reason": reason,
        "prev_hash": _prev_hash(store, session_id),
        "schema_versions": {"ttt": s["schema"]},
        "gw_sig": None,
        "auditor_sig": None,
    }
    body["gw_sig"] = "ed25519:" + crypto.sign(gw_priv, signing_bytes(body))
    store.save_receipt(session_id, "round", round_n, body, published=False)
    return body


def emit_game_receipt(store, gw_keys, session_id):
    """Build, gateway-sign, and store (unpublished) the final game receipt."""
    gw_priv, _gw_pub = gw_keys
    s = store.get_session(session_id)
    last = store.get_receipt(session_id, "round", s["round"])
    body = {
        "session": session_id,
        "rounds_played": s["round"],
        "final_board": list(s["board"]),
        "result": last["body"]["result"],
        "prev_hash": _prev_hash(store, session_id),
        "schema_versions": {"ttt": s["schema"]},
        "gw_sig": None,
        "auditor_sig": None,
    }
    body["gw_sig"] = "ed25519:" + crypto.sign(gw_priv, signing_bytes(body))
    store.save_receipt(session_id, "game", s["round"], body, published=False)
    return body


def countersign(store, gw_keys, auditor_id, session_id, payload):
    """gw.countersign {session, round, auditor_sig, kind?}.

    The auditor countersigns a receipt it has independently verified. The
    signature covers the canonical receipt bytes with signature fields
    removed. Publishing a round receipt opens the next round (or issues the
    game receipt when the game ended); publishing the game receipt finishes
    the session.
    """
    gw_priv, _gw_pub = gw_keys
    s = store.get_session(session_id)
    if not s:
        return None, wire.AppError("not_found", "unknown session", 404)
    if s["status"] != "active":
        return None, wire.AppError("forbidden",
                                   "session is not active", 403)
    if auditor_id != s["auditor_id"]:
        return None, wire.AppError("forbidden",
                                   "only this session's auditor countersigns",
                                   403)
    kind = payload.get("kind") or "round"
    if kind not in ("round", "game"):
        return None, wire.AppError("bad_request", 'kind must be "round" or "game"')
    round_n = payload.get("round")
    r = store.get_receipt(session_id, kind, round_n)
    if not r:
        return None, wire.AppError("not_found", "unknown receipt", 404)
    if r["published"]:
        return {"session": session_id, "kind": kind, "round": round_n,
                "countersigned": True}, None
    sig_hex = wire.split_sig(payload.get("auditor_sig"))
    if not sig_hex:
        return None, wire.AppError(
            "bad_request", 'auditor_sig must look like "ed25519:<128 hex>"')
    auditor = store.get_agent(auditor_id)
    if not crypto.verify(auditor["pubkey"], signing_bytes(r["body"]), sig_hex):
        return None, wire.AppError("bad_signature",
                                   "auditor signature does not verify")
    body = dict(r["body"])
    body["auditor_sig"] = "ed25519:" + sig_hex
    store.mark_receipt_published(session_id, kind, round_n, body)

    if kind == "round":
        if body["game_over"]:
            game_body = emit_game_receipt(store, gw_keys, session_id)
            store.update_session(session_id, {
                "countersign_deadline": time.time() + s["reveal_timeout_s"]})
            _push_game_receipt(store, gw_keys, session_id, game_body)
            store.log_event("receipt.published",
                            "Round %d receipt published; game receipt issued"
                            % round_n, session_id=session_id)
        else:
            store.update_session(session_id, {
                "phase": "commit", "round": round_n + 1,
                "commit_deadline": None, "reveal_deadline": None,
                "countersign_deadline": None})
            store.create_round({"session_id": session_id, "n": round_n + 1})
            store.log_event("receipt.published",
                            "Round %d receipt published; round %d opened"
                            % (round_n, round_n + 1), session_id=session_id)
    else:
        store.update_session(session_id, {"status": "finished", "phase": "done"})
        store.log_event("game.finished",
                        "Game over: %s" % body["result"], session_id=session_id)
    return {"session": session_id, "kind": kind, "round": round_n,
            "countersigned": True}, None


def _push_game_receipt(store, gw_keys, session_id, game_body):
    gw_priv, _gw_pub = gw_keys
    s = store.get_session(session_id)
    for rid in (s["a_id"], s["b_id"], s["auditor_id"]):
        env = wire.make_gateway_envelope(gw_priv, rid, "ttt.game_receipt",
                                         game_body, schema="receipts/1",
                                         session=session_id)
        store.push_envelope(rid, session_id, "ttt.game_receipt", env)


def export(store, session_id):
    """gw.receipts: {session, receipts} -- published receipts in chain
    order (round receipts, then the game receipt)."""
    return {"session": session_id,
            "receipts": store.published_receipts(session_id)}
