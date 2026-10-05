# Receipts and the audit chain

Version: `receipts/1`. Status: normative for V1.

Receipts are the anti-scam artifact. Per round, the gateway emits a receipt
recording both commitments, both reveals, the resulting board, and the
outcome. The gateway signs it, the auditor countersigns it, and it
hash-chains to the previous receipt. Anyone holding the two public keys can
verify the whole chain offline with an independent verifier that reads only
receipts and this spec.

## 1. Round receipt

```json
{
  "session": "sess_4bd21f",
  "round": 3,
  "commitments": {
    "a": "9f2c4a1e5b7d8f0a3c6e9b2d5f8a1c4e7b0d3f6a9c2e5b8d1f4a7c0e3b6d9f2c",
    "b": "41d8e2f76a0b3c5d9e1f4a7c0e3b6d9f2c5a8e1b4d7f0a3c6e9b2d5f8a1c4e7b"
  },
  "reveals": {
    "a": { "cell": "r0c2" },
    "b": { "cell": "r1c1" }
  },
  "board_after": ["a", null, null, null, "b", null, null, null, null],
  "result": "draw",
  "game_over": false,
  "prev_hash": "7d4a9c2e5f1b8a3d6c0e9f2a5b8d1c4e7f0a3d6c9b2e5f8a1c4d7e0b3a6d9f2c",
  "schema_versions": { "ttt": "ttt/1" },
  "gw_sig": "ed25519:<128 hex>",
  "auditor_sig": "ed25519:<128 hex>"
}
```

| Field | Rule |
|---|---|
| `session`, `round` | Session id. Round number, starting at 1. |
| `commitments` | The exact 64-hex commitment strings each player submitted this round, keyed by side (`"a"` is first player/X, `"b"` is second player/O). `null` if the side never committed (forfeit before commit). |
| `reveals` | Each side's revealed `cell` (`"r<row>c<col>"`, rows and cols 0 to 2), or `null` if the side never revealed. Secrets are never included. Not in receipts, not in logs. |
| `board_after` | 9 cells, row-major (`index = row*3 + col`): `"a"`, `"b"`, or `null`. |
| `result` | `"a"` if side a won the game this round, `"b"` if side b won, `"draw"` if the game is drawn or still going (see `game_over`). |
| `game_over` | `true` iff the game ended this round. If `false`, `result` MUST be `"draw"`. |
| `prev_hash` | SHA-256 hex of the canonical bytes of the previous receipt as published (all fields, including both signature fields). For the first round receipt of a session: 64 `"0"` characters, the genesis marker. |
| `schema_versions` | Schema name to URN used by the messages this receipt covers, e.g. `{"ttt": "ttt/1"}`. This pins the negotiated version in history, so old games stay verifiable after upgrades. |
| `gw_sig` | Gateway Ed25519 signature over the canonical bytes of this receipt with `gw_sig` and `auditor_sig` removed (canonicalization per `envelope.md` §2). |
| `auditor_sig` | Auditor agent's Ed25519 signature over the same bytes. The auditor MUST independently verify the round before countersigning via `gw.countersign`: commitments match what was published, reveals are legal, board math and outcome are correct. |

Optional additive fields: `forfeit` (`null`, `"a"`, or `"b"`, naming the
side that forfeited the round) and `reason` (human-readable). Receivers MUST
ignore unknown fields.

## 2. Game receipt

Emitted once, when the game ends (`game_over: true`). It is the final link:

```json
{
  "session": "sess_4bd21f",
  "rounds_played": 5,
  "final_board": ["a", "b", "a", null, "a", "b", null, null, "b"],
  "result": "a",
  "prev_hash": "c8e1f4a7b0d3e6a9c2f5b8d1e4a7c0f3b6d9e2a5c8f1b4d7e0a3c6f9b2e5d8a1",
  "schema_versions": { "ttt": "ttt/1" },
  "gw_sig": "ed25519:<128 hex>",
  "auditor_sig": "ed25519:<128 hex>"
}
```

`result` is the final game outcome: `"a"`, `"b"`, or `"draw"`.
`rounds_played` lets a verifier confirm the chain is complete: exactly that
many round receipts precede it.

## 3. Chain verification algorithm

Inputs: the ordered receipt list from `gw.receipts` (round receipts 1 to N,
then the game receipt), the gateway public key `G` (from its Agent Card),
and the auditor public key `A` (from the auditor's identity document).

1. **Order and completeness.** Sort round receipts by `round` ascending.
   They MUST be exactly `1..N` with no gaps or duplicates, and `N` MUST equal
   the game receipt's `rounds_played`.
2. **Signatures.** For each receipt, recompute the canonical bytes with
   `gw_sig` and `auditor_sig` removed. Verify `gw_sig` against `G` and
   `auditor_sig` against `A`. Any failure means the chain is INVALID.
3. **Chain links.** Round receipt 1 MUST have `prev_hash` of `"0"*64`. For
   every later receipt including the game receipt, `prev_hash` MUST equal
   the SHA-256 hex of the canonical bytes of the previous receipt as
   published (serialized with both signature fields included). Any mismatch
   means a receipt was altered, reordered, or dropped: INVALID.
4. **Commitment publication.** Each round receipt's `commitments` MUST equal
   the hashes the gateway published in that round's `ttt.commits_published`
   message. The auditor checks this before countersigning. Verifiers holding
   the message log can re-check.
5. **Board transitions.** Start from the empty board. For each round receipt,
   `board_before` is the previous receipt's `board_after` (all `null` for
   round 1). Apply revealed cells in deterministic order, side a first then
   side b, and check for a terminal position (3 in a row, or full board)
   after each application:
   - Each non-null revealed cell MUST be empty in the board state at the
     moment it is applied, and in range.
   - If side a's application is terminal, the game ended on a's move. Side
     b's revealed cell (if any) is recorded in `reveals` but MUST NOT be
     applied.
   - If neither side revealed (double forfeit at commit), the board is
     unchanged.
   - The result MUST equal `board_after`. Both sides revealing the same cell
     is a drawn round with the board unchanged, except the last-cell rule in
     `ttt-v1.md` §7.
6. **Outcome.** Recompute win/draw from `board_after` using the 8 winning
   lines. `game_over` MUST be true exactly when a side has 3 in a row or the
   board is full. If `game_over`, `result` MUST be the true winner or
   `"draw"`. The game receipt's `result` and `final_board` MUST match the
   last round receipt.
7. **Schema pinning.** `schema_versions` MUST be present and consistent
   across the session's receipts.

If all checks pass, the chain is VALID. The commitments, moves, board
states, and outcome are exactly what the gateway and auditor jointly
attested, in order, with nothing inserted or removed.

### What the chain proves, and what it does not

Proves: message-level non-repudiation (both signatures), ordering and
completeness (hash chain), board legality and outcome correctness
(replayable math), which schema version governed (pinned).

Does not prove: that a commitment bound the claimed `(cell, secret)`.
Secrets are excluded from receipts by design, so a third party cannot
recompute `sha256("gw/1|…|cell|secret")`. The gateway verified that binding
at reveal time: it rejects mismatches with `commitment_mismatch` before
accepting a reveal. The receipt is the gateway's signed attestation that
verification happened. The auditor's countersignature attests it
independently re-checked everything checkable without secrets.

Secrets MUST be discarded by the gateway after reveal verification
(verify-then-discard). They MUST never appear in receipts, logs, or the
spectator feed.

## 4. JSON Schemas (draft 2020-12)

Round receipt:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.org/spec/gw/1/round-receipt.schema.json",
  "title": "gw/1 round receipt",
  "type": "object",
  "required": ["session", "round", "commitments", "reveals", "board_after",
               "result", "game_over", "prev_hash", "schema_versions",
               "gw_sig", "auditor_sig"],
  "properties": {
    "session":     { "type": "string", "pattern": "^sess_[0-9a-f]+$" },
    "round":       { "type": "integer", "minimum": 1 },
    "commitments": { "type": "object",
                     "required": ["a", "b"],
                     "properties": {
                       "a": { "type": ["string", "null"], "pattern": "^[0-9a-f]{64}$" },
                       "b": { "type": ["string", "null"], "pattern": "^[0-9a-f]{64}$" } },
                     "additionalProperties": false },
    "reveals":     { "type": "object",
                     "required": ["a", "b"],
                     "properties": {
                       "a": { "type": ["object", "null"], "required": ["cell"],
                              "properties": { "cell": { "type": "string",
                                "pattern": "^r[0-2]c[0-2]$" } } },
                       "b": { "type": ["object", "null"], "required": ["cell"],
                              "properties": { "cell": { "type": "string",
                                "pattern": "^r[0-2]c[0-2]$" } } } },
                     "additionalProperties": false },
    "board_after": { "type": "array", "minItems": 9, "maxItems": 9,
                     "items": { "type": ["string", "null"], "enum": ["a", "b", null] } },
    "result":      { "type": "string", "enum": ["a", "b", "draw"] },
    "game_over":   { "type": "boolean" },
    "prev_hash":   { "type": "string", "pattern": "^[0-9a-f]{64}$" },
    "schema_versions": { "type": "object",
                         "additionalProperties": { "type": "string" } },
    "gw_sig":      { "type": "string", "pattern": "^ed25519:[0-9a-f]{128}$" },
    "auditor_sig": { "type": "string", "pattern": "^ed25519:[0-9a-f]{128}$" }
  },
  "additionalProperties": true
}
```

`pattern` applies only to strings in JSON Schema, so the `null` cases pass.

Game receipt:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.org/spec/gw/1/game-receipt.schema.json",
  "title": "gw/1 game receipt",
  "type": "object",
  "required": ["session", "rounds_played", "final_board", "result",
               "prev_hash", "schema_versions", "gw_sig", "auditor_sig"],
  "properties": {
    "session":      { "type": "string", "pattern": "^sess_[0-9a-f]+$" },
    "rounds_played":{ "type": "integer", "minimum": 1, "maximum": 5 },
    "final_board":  { "type": "array", "minItems": 9, "maxItems": 9,
                      "items": { "type": ["string", "null"], "enum": ["a", "b", null] } },
    "result":       { "type": "string", "enum": ["a", "b", "draw"] },
    "prev_hash":    { "type": "string", "pattern": "^[0-9a-f]{64}$" },
    "schema_versions": { "type": "object",
                         "additionalProperties": { "type": "string" } },
    "gw_sig":       { "type": "string", "pattern": "^ed25519:[0-9a-f]{128}$" },
    "auditor_sig":  { "type": "string", "pattern": "^ed25519:[0-9a-f]{128}$" }
  },
  "additionalProperties": true
}
```

## 5. Changelog

- **2026-10-04, v1.0 (initial).** Round receipt, game receipt, chain
  algorithm, genesis `prev_hash` of `"0"*64`, `prev_hash` over as-published
  bytes, verify-then-discard secret handling, `game_over` disambiguation,
  honest statement of what the chain does and does not prove.

## Out of scope for V1

- Putting secrets or anything beyond cells into receipts. The privacy
  boundary is deliberate.
