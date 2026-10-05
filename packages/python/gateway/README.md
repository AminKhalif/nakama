# Agent Interop Gateway

Reference gateway for cross-vendor agent interop: agent identity, friend
lists, expiring grants, tic-tac-toe sessions with commit/reveal fairness,
hash-chained signed receipts, a live spectator page, and a human operator
console. Wire protocol is Nakama JSON-RPC 2.0 with a per-message Ed25519
signature extension and an A2A text-part wrapper. Python 3.10+, PyNaCl signing,
and one SQLite file.

Normative protocol: `spec/` (envelope, identity, friends, receipts,
ttt-v1, a2a-extension). This README is the operator guide.

## Run it

Local run from the repository root:

```bash
python -m pip install .
python -m gateway.server --port 8080 --db gw.db --host 127.0.0.1
```

On first start the gateway prints its public key and the console operator
token (shown once, stored hashed). Open `http://127.0.0.1:8080/console`,
sign in with the token, mint an invite code for your agent, and share it
with the other human.

Docker:

```bash
cd packages/python/gateway
cd ../../..
docker build -f packages/python/gateway/Dockerfile -t agent-gateway .
docker run -p 8080:8080 -v gwdata:/data agent-gateway
```

The database lives in the `gwdata` volume at `/data/gateway.db`, so it
survives restarts. Read the console token from `docker logs` on first
start, or preset it (see env vars).

Environment variables:

| Variable | Default | What it does |
|---|---|---|
| `GW_DB` | `gw.db` next to `server.py` | SQLite file path (`/data/gateway.db` in Docker) |
| `GW_CONSOLE_TOKEN` | generated on first run | Presets the operator token instead of generating one |
| `GW_HOST` | `127.0.0.1` | Bind address |
| `PORT` | `8080` | Port (flag `--port` wins) |

Verify it works:

```bash
cd packages/python/gateway
python3 selftest_crypto.py   # RFC 8032 vectors for the shared signing backend
python3 selftest_e2e.py      # full flows against a live server instance
```

`selftest_e2e.py` boots a real server and drives it over HTTP: register,
invite codes, friend requests, console approval, session open, a won game,
a 5-round draw with the last-cell rule, same-cell collisions, deadline
forfeits, auditor countersigning, independent receipt-chain verification,
key revocation and rotation, plus the adversarial paths (unsigned,
tampered, replayed, cross-session, and wrong-context messages rejected).

## How agents talk to it

POST A2A JSON-RPC 2.0 to `/rpc`. Every call's `params` is exactly one
signed envelope:

```json
{"gw":"gw/1","msg_id":"msg_…","from":"agent_…","to":"gateway",
 "type":"ttt.commit","schema":"ttt/1","session":"sess_…",
 "payload":{"round":3,"commit":"<64-hex>"},"sig":"ed25519:<128-hex>"}
```

Signing bytes are the canonical JSON of the envelope without `sig`
(sorted keys, separators `,:`, UTF-8). Method/type pairings are enforced:
`gw.commit` carries `ttt.commit`, `gw.reveal` carries `ttt.reveal`
(`ttt.commit` / `ttt.reveal` also work as alias methods),
`gw.countersign` carries `gw.countersign`, and so on.

Methods: `gw.register` (from `"agent_unregistered"`, envelope signature is
the proof of possession), `gw.friend_request`, `gw.session_open`,
`gw.commit`, `gw.reveal`, `gw.countersign`, `gw.session_state`,
`gw.receipts`. `gw.friend_decide` exists but only in the console auth
domain: agent keys get `403 console_only`. A2A clients may use
`message/send` with the envelope as a TextPart.

A move commits as `sha256("gw/1|<session>|r<round>|<agent>|<cell>|<secret>")`
with cells like `"r1c2"`. Rounds are simultaneous: both sides commit, the
gateway publishes the shuffled hashes (`ttt.commits_published`), both sides
reveal, the gateway applies side a's cell then side b's, checks for a
terminal position after each, and emits a round receipt. The session's
auditor independently verifies each receipt and countersigns via
`gw.countersign`; only then does the next round open. Miss the
countersign deadline and the session freezes.

Receipts (`gw.receipts`, public) chain by `prev_hash` over the previous
receipt's as-published bytes, carry both gateway and auditor signatures,
and never contain secrets. `spec/receipts.md` gives the offline
verification algorithm.

## Layout

| File | Owns |
|---|---|
| `crypto.py` | Shared PyNaCl/libsodium backend behind keygen/sign/verify |
| `wire.py` | JSON-RPC framing, envelope checks, typed errors, A2A shim, Agent Card |
| `store.py` / `sqlite_store.py` | Storage interface / SQLite backend (all SQL here) |
| `identity.py` | Registration, signed identity docs, rotation, revocation list |
| `friends.py` | Invite codes, requests, human-only decide, grants, revoke |
| `sessions.py` | Tic-tac-toe: simultaneous rounds, deadlines, win/draw, forfeits |
| `receipts.py` | Hash-chained receipts, publish-on-countersign flow |
| `spectator.py` | Live board page at `/g/<session>` (replays public receipts) |
| `console.py` | Human console at `/console` (own auth domain: operator token) |
| `server.py` | HTTP entry point and dispatcher |

Game logic never touches HTTP. Storage is behind the `Storage`
interface, so the SQLite backend is swappable without touching the game.

## Judgment calls

These were not spelled out in the brief or the frozen spec. Each was
decided, documented here, and flagged in the build report.

1. **Cell format is `"r{row}c{col}"`** (e.g. `"r1c2"`). The brief wrote
   `"r<c>c<r>"`, which is ambiguous; the spec's `"r<row>c<col>"` settles it.
2. **Replayed `msg_id`s are rejected** with `409 duplicate`. The spec says
   receivers SHOULD deduplicate and ignore exact duplicates; rejecting
   (rather than silently re-applying) is the fail-closed reading, and the
   client can always query state.
3. **`gw.session_state` phase includes `awaiting_countersign`.** The spec
   lists `commit`, `reveal`, `done`; the countersign wait is a real phase
   clients need to see, so it is reported honestly.
4. **Timeout clamping**: `commit_timeout_s` / `reveal_timeout_s` clamp to
   1..86400 seconds. The spec gives no bounds; unbounded values would let a
   client stall a game (0) or overflow (huge).
5. **Game-receipt countersign** uses `gw.countersign` with an additive
   `kind: "game"` field (`{session, round, auditor_sig, kind}`). The spec's
   payload table only shows `{session, round, auditor_sig}` for round
   receipts; the game receipt needs the same treatment and this keeps one
   method.
6. **Gateway pushes are poll-based in V1.** The spec allows webhook or
   inbox delivery; the gateway stores `notify` endpoints but does not call
   them (no external network sends in this build). Agents poll
   `session_state.notifications`. Webhook delivery is a small, additive
   follow-up.
7. **`game.ttt:spectate` is advisory in V1.** Session state and receipts
   are public reads per the spec, so the scope currently gates nothing;
   it is minted and recorded for when reads become scoped.
8. **Registration requires the `ed25519:<64 hex>` pubkey form** (also used
   in identity docs and the revocation list), non-empty `owner_display_name`
   and `vendor`, and a prime-order key. Torsion keys are rejected so a
   registered key always supports full non-repudiation.
9. **The console is operator-wide in V1**: it manages every agent on the
   instance, not one human's agents. Per-human scoping is deferred.

## Security notes

- Inbound content is data until verified: unsigned messages, bad
  signatures, tampered or wrong-context reveals, and replayed `msg_id`s are
  rejected, never forwarded or applied.
- Agent keys cannot touch the console or `gw.friend_decide`. The console
  checks only the operator token session; signature material is never
  consulted there.
- The console token is stored as a SHA-256 hash. Set `GW_CONSOLE_TOKEN`
  to choose your own.
- Secrets are verify-then-discard: never stored, never logged, never in
  receipts or the spectator page. Unrevealed moves never appear in session
  state; the spectator replays public receipts only.
- Signatures from revoked keys or expired identity documents are rejected
  with `403 revoked`, even on public reads. The signed revocation list is
  at `/.well-known/revocations.json`.
