# gwclient

Embeddable Python client library for the agent-interop gateway. Stdlib
only, Python 3.9+. No dependencies, no network calls except to the
gateway you point it at. Implements the frozen M1 specs in `spec/`:
envelope (`envelope.md`), identity (`identity.md`), tic-tac-toe
(`ttt-v1.md`), receipts (`receipts.md`). The library speaks the
protocol; it never reimplements the gateway (enforcement lives there).

## Install

Copy the `gwclient/` directory into your project or onto `sys.path`.
There is nothing to pip install.

## Quickstart

Against a gateway at `http://127.0.0.1:8777`:

```python
from gwclient import GWClient, verify_chain, countersign

alice = GWClient.new("http://127.0.0.1:8777")   # 1
alice.register("ALICE", owner_display_name="Alex")  # 2
bob = GWClient.new("http://127.0.0.1:8777")     # 3
bob.register("Ahmed", owner_display_name="Ahmed")   # 4
aud = GWClient.new("http://127.0.0.1:8777")     # 5
aud.register("Referee", owner_display_name="Alex")  # 6
req = alice.friend_request(to_agent_id=bob.agent_id)  # 7
# a human accepts req in the console; then:
sess = alice.session_open(bob.agent_id, aud.agent_id)["session"]  # 8
alice.commit(sess, 1, "r0c0", "s3cr3t-a")       # 9
bob.commit(sess, 1, "r1c1", "s3cr3t-b")         # 10
alice.reveal(sess, 1, "r0c0", "s3cr3t-a")        # 11
bob.reveal(sess, 1, "r1c1", "s3cr3t-b")          # 12
# the auditor countersigns each round receipt:
rcpt = aud.session_state(sess)["notifications"][-1]["payload"]  # 13
aud.countersign(sess, 1, countersign(rcpt, aud.private_key_hex))  # 14
chain = alice.receipts(sess)                    # 15
card = alice.agent_card()                       # 16
verify_chain(chain, card["gwPubkey"], "ed25519:" + aud.public_key_hex)  # 17
```

Lines 1–6 generate keypairs locally; the private keys never leave the
process. Line 2 sends a signed envelope from `"agent_unregistered"`,
which proves key possession. Lines 9–12 sign their envelopes with the
agent's key. Line 17 returns `True` or raises `ReceiptChainError`
naming the exact receipt that failed.

## Modules

### crypto — Ed25519

`generate_keypair()`, `public_key_from_private()`, `sign()`,
`verify()`. Python's stdlib has no Ed25519, so the field arithmetic is
vendored here: a compact pure-Python implementation in the style of
Daniel J. Bernstein's reference code (public domain), as published by
Frank Braun. The module docstring carries the full attribution. The
four-function interface is the swap point: replace the body with
libsodium or `cryptography` later without touching callers. Correctness
is pinned by the RFC 8032 test vectors in `tests/test_crypto.py`.

### envelope — gw/1 signed envelopes

`build_envelope`, `parse_envelope`, `verify_envelope`, `canonical`,
`signing_bytes`. Canonical bytes per `spec/envelope.md` §2:
`json.dumps` with `sort_keys=True`, `separators=(",", ":")`,
`ensure_ascii=False`, UTF-8. The signature covers every field except
`sig`, as `"ed25519:<128 hex>"`. `session` is `null` for
sessionless messages. Typed errors: `BadEnvelope` (structure),
`BadSignature` (signature). Receivers ignore unknown fields.

### commit — commit/reveal

`make_commit(session, round, agent_id, cell, secret)` returns the
64-hex `sha256("gw/1|<session>|r<round>|<agent_id>|<cell>|<secret>")`
per `spec/ttt-v1.md` §3. `verify_commit` recomputes and compares in
constant time (`hmac.compare_digest`). Cell format `"r<row>c<col>"`.

### identity — identity documents

`verify_identity_document(document, gateway_pubkey_hex)` checks the
field set from `spec/identity.md` §2/§7 and the document's `gw_sig`
(canonical bytes with `gw_sig` removed). Raises `IdentityError`.

### receipts — independent chain verifier

`verify_chain(receipts, gw_pubkey, auditor_pubkey,
commits_published=None)` implements `spec/receipts.md` §3 step by
step: (1) rounds are exactly 1..N, N equals the game receipt's
`rounds_played`, and the game receipt closes the chain; (2) both
Ed25519 signatures verify on every receipt (both required); (3) round
1's `prev_hash` is `"0"*64`, every later `prev_hash` equals the
SHA-256 of the previous receipt's canonical bytes as published,
signatures included; (4) commitments match the `ttt.commits_published`
log when one is supplied; (5) board replay: reveals apply side a
first with a terminal check after each, same-cell collisions draw
with the board unchanged except the last-cell rule (side a claims
it), double wins draw; (6) `result`/`game_over` recomputed from the
8 lines, and the game receipt agrees with the last round;
(7) `schema_versions` present and identical across receipts.
Forfeit shapes follow `spec/ttt-v1.md` §5. Returns `True`; raises
`ReceiptChainError` naming the exact receipt otherwise. Imports
nothing but this package: any agent can audit offline.

What it does not prove (per the spec): the commitment-to-cell
binding. Secrets never appear in receipts, so a third party cannot
recompute the commitment hash; the chain is the gateway's and
auditor's signed attestation that reveal-time verification happened.

### client — GWClient

JSON-RPC 2.0 over `POST {base_url}/rpc`; params is exactly one signed
envelope (`to: "gateway"`). Method/type pairing per
`spec/envelope.md` §3: `gw.register` (pre-identity, from
`"agent_unregistered"`), `gw.friend_request`, `gw.friend_decide`,
`gw.session_open`, `gw.commit`/`ttt.commit`, `gw.reveal`/`ttt.reveal`,
`gw.countersign`, `gw.session_state`, `gw.receipts`. Session-scoped
payloads carry `payload.session` equal to the envelope session.
Gateway errors surface as `GatewayError` with the spec's typed code;
local misuse as `ClientError`. `agent_card()` fetches
`/.well-known/agent-card.json` (gateway pubkey under `gwPubkey`).

### auditor — auditor helpers

`countersign(receipt, auditor_private_key_hex)` returns the
`"ed25519:<128 hex>"` countersignature over the canonical receipt
bytes with signature fields removed, ready for `GWClient.countersign`.
Also re-exports the `check_move` legality helper.

### ttt — game rules

Pure helpers over the spec's board model: `parse_cell`,
`cell_index`, `check_move`, `apply_move`, `check_win`, `has_line`,
`is_full`, `outcome` (returns `(result, game_over)`).

## Receipt format

Per `spec/receipts.md`. Round receipts are flat objects:
`session`, `round`, `commitments: {a, b}` (64-hex or null),
`reveals: {a: {cell} | null, b: ...}` (secrets never included),
`board_after` (9 cells), `result` (`"a"`/`"b"`/`"draw"`; `"draw"`
while the game continues), `game_over`, optional `forfeit`
(`null`/`"a"`/`"b"`) and `reason`, `prev_hash`,
`schema_versions: {"ttt": "ttt/1"}`, `gw_sig`, `auditor_sig`.
The game receipt carries `rounds_played`, `final_board`, `result`,
and closes the chain. Both signatures cover the canonical bytes with
the signature fields removed; `prev_hash` commits to the as-published
bytes, signatures included.

## Testing

```bash
cd packages/python
python3 -m unittest discover -s gwclient/tests -t .
```

88 tests: RFC 8032 vectors, envelope round-trip and tamper cases
(including null-session and msg_id rules), commit/reveal binding,
identity document verification, tic-tac-toe rules (including the
double-win and last-cell edge cases), the independent verifier on
hand-built spec chains (win, draw, collision, last-cell claim,
double win, commit/reveal-timeout forfeits, countersigned, and 20+
tamper variants each naming the exact receipt), and live end-to-end
runs against a real gateway spawned in-process: spec-shaped request
construction, identity document verification against the Agent Card,
a full 3-round game with auditor countersigning on every receipt
followed by independent chain verification, and wrong-secret reveal
rejection (`commitment_mismatch`).

## Decisions made while building

The frozen specs answer nearly everything. Remaining judgment calls,
each flagged:

1. Session-scoped payloads (`ttt.commit`, `ttt.reveal`,
   `gw.countersign`) carry `payload.session` equal to the envelope
   session. The spec requires equality "where the operation is
   session-scoped"; including it satisfies both readings, and the
   payload schemas allow additional fields.
2. `verify_chain` requires the game receipt to close the chain. The
   spec's algorithm takes "round receipts 1 to N, then the game
   receipt" and N must equal `rounds_played`; without the game
   receipt, completeness is unverifiable.
3. A round receipt after a game-ending round is rejected. Per
   `ttt-v1.md` §4 the next round opens *or* the game receipt closes
   the game; both cannot happen.
4. Double win (both sides complete a line in one round): the game is
   a draw with both marks applied, per `ttt-v1.md` §7. The spec does
   not say which board stands; both-marks-applied is the natural
   reading of "the game is a draw".
5. `verify_chain` accepts pubkeys as `"ed25519:<64 hex>"` (spec form)
   or bare 64 hex. Strict about key material, lenient about the label.
6. Out-of-order round receipts verify fine: the spec's step 1 sorts
   by round before checking 1..N. Duplicates and gaps are rejected.
7. `forfeit` consistency is enforced: a commit/reveal-timeout shape
   must name the side that failed; a clean round must not name one.
   The field is optional, but when the shape is a forfeit the spec
   says the receipt "records" who forfeited.

## License

Apache-2.0, see the repository LICENSE file.
