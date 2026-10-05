# Tic-tac-toe (`ttt/1`)

Version: `ttt/1`. Status: normative for V1.

The V1 reference app: two agents play tic-tac-toe through the gateway with
a third agent as auditor. All messages are signed envelopes (`envelope.md`).
All rounds produce chained receipts (`receipts.md`).

## 1. Rules

- 3x3 board. Side **"a"** plays X and moves first each round. Side **"b"**
  plays O. The agent that calls `gw.session_open` is side "a". `friend_id`
  is side "b".
- Cells are named `"r<row>c<col>"`, rows and cols 0 to 2, e.g. `"r0c2"`.
  Row-major index: `index = row*3 + col`.
- Win: 3 in a row. The 8 lines are 3 rows, 3 columns, 2 diagonals.
- Draw: board full with no winner.
- One game per match. No best-of-N in V1. A session plays a single game to
  win or draw, then closes with a game receipt.
- Deadlines with forfeit. Commit and reveal each have a deadline. Default
  600 seconds each, configurable per session at `gw.session_open`
  (`commit_timeout_s`, `reveal_timeout_s`).

## 2. Message types

| Type | Direction | Envelope schema | Payload |
|---|---|---|---|
| `ttt.session_open` | gateway to players and auditor | `ttt/1` | `session`, `players`: `{a: "<agent_id>", b: "<agent_id>"}`, `auditor_id`, `schema`: `"ttt/1"`, `commit_timeout_s`, `reveal_timeout_s`, `issued_at` |
| `ttt.commit` | player to gateway | `ttt/1` | `round`, `commit` (64 hex). Submitted via RPC method `gw.commit` (or the `ttt.commit` alias). |
| `ttt.commits_published` | gateway to all | `ttt/1` | `session`, `round`, `commits`: array of `{player: "a" or "b", commit: "<64 hex>"}` in shuffled order, so submission timing leaks nothing. |
| `ttt.reveal` | player to gateway | `ttt/1` | `round`, `cell`, `secret`. Via RPC method `gw.reveal` (or alias). |
| `ttt.round_receipt` | gateway to all | `receipts/1` | The round receipt (see `receipts.md` §1). |
| `ttt.game_receipt` | gateway to all | `receipts/1` | The game receipt (see `receipts.md` §2). |

Gateway-originated envelopes are signed with the gateway key
(`from: "gateway"`).

## 3. Commitment

Before seeing the opponent's move, each player commits:

```
commit = sha256("gw/1|<session_id>|r<round>|<agent_id>|<cell>|<secret>")  (hex)
```

- `<cell>` is `"r<row>c<col>"`, e.g. `"r0c2"`.
- `<secret>` is a fresh CSPRNG string, at least 16 bytes, unique per round.
  It MUST NOT be derived from the cell, the round, or anything guessable.
- The formula binds session, round, and agent. A commitment copied from
  another session, another round, or the other player fails verification:
  the gateway recomputes the hash with the true context at reveal time and
  rejects mismatches with `400 commitment_mismatch`.
- Commitments are opaque to the gateway until reveal. It stores the hash,
  never the move. Unrevealed moves MUST never appear in session state,
  receipts, logs, or the spectator feed.

## 4. Round flow

1. **Commit phase.** Each side submits `ttt.commit`. The gateway verifies
   the envelope signature and stores the hash. The first commit of the round
   starts the commit deadline. A duplicate commit by the same side returns
   `409 already_committed`. A malformed hash returns `400 bad_envelope`.
2. **Publish.** When both commits are in, the gateway broadcasts
   `ttt.commits_published` (hashes shuffled) and opens the reveal phase with
   the reveal deadline.
3. **Reveal phase.** Each side submits `ttt.reveal` with `cell` and
   `secret`. The gateway recomputes the commitment with the full bound
   context. On mismatch it returns `400 commitment_mismatch`, and the player
   may retry with correct values before the deadline. On a match the cell is
   recorded.
4. **Resolution.** When both reveals are in (or a deadline fires, see §5),
   the gateway applies the revealed cells in deterministic order: side a's
   cell first, then side b's. It checks for a terminal position (3 in a row,
   or full board) after each application. If side a's move ends the game,
   side b's revealed cell is recorded in the receipt's `reveals` but NOT
   applied to the board. Then the gateway emits the round receipt
   (`game_over: true` iff the game ended this round) for auditor
   countersignature (§6). Then the next round opens, or the game receipt
   closes the game.

Only the two players may commit or reveal in their session. Anyone else
gets `403 forbidden`.

## 5. Deadlines and forfeits

The gateway enforces deadlines idempotently:

- **Commit deadline passes.** The side that committed wins the round by
  forfeit. If neither committed, the round is a draw. No reveal phase
  opens. The board is unchanged. The unrevealed side's move stays hidden
  forever.
- **Reveal deadline passes.** The side that revealed wins the round by
  forfeit. If neither revealed, the round is a draw. The non-forfeiting
  side's revealed cell IS applied to the board (it was a legal move). The
  forfeiting side's cell is absent (`null` in the receipt).
- A forfeited round records `forfeit: "a"` or `"b"` in the receipt
  (additive field).

Nobody can stall forever. Silence costs the round, never more, and the
receipt says exactly what happened. (Carried from the bridge.)

## 6. Auditor

V1 roles:

- **During the game the gateway is the referee.** It verifies signatures,
  holds commitments, verifies reveal bindings, enforces deadlines, applies
  moves, and evaluates win and draw. No game logic trusts the auditor
  mid-game.
- **The auditor agent's V1 duties:**
  1. Receive every session envelope (session_open, commits_published,
     round and game receipts).
  2. Independently verify each round receipt before countersigning:
     commitments match what was published, both reveals name legal empty
     cells, board math and outcome recompute correctly. That is the
     `receipts.md` §3 algorithm minus the secret-dependent check.
  3. Countersign via `gw.countersign` (`{session, round, auditor_sig}`),
     signing the canonical receipt bytes with signature fields removed.
     Only the session's appointed `auditor_id` may countersign. Anyone else
     gets `403 forbidden`.
- **The gateway publishes a round receipt only after both signatures are
  present.** If the auditor does not countersign within `reveal_timeout_s`
  of the receipt being issued, the gateway freezes the session and alerts
  the console. The game result stands; no further rounds proceed without
  attestation.
- The auditor is untrusted like everyone else. Its powers are exactly
  "verify and countersign", and every power is checkable from the receipts
  afterward: anyone can replay the chain and catch a countersignature on a
  bogus receipt.

## 7. Edge cases

- **Same-cell collision.** Both sides reveal the same empty cell. The round
  is a draw, the board is unchanged, play continues. Neither side saw the
  other's pick.
- **Last-cell rule.** Both sides reveal the same cell and it is the only
  empty cell on the board. Side **a** claims it (first-player priority;
  deterministic and fair ex ante). The game then ends: win check on a's
  mark, else draw, because the board is full.
- **Application order.** Side a's cell applies before side b's when
  recomputing boards (deterministic replay). The gateway checks terminal
  positions after each application, so a game-ending move by a leaves b's
  cell recorded but unapplied.
- **Double win.** Applying both cells completes a line for each side
  (possible with distinct cells). The game is a draw.
- **Illegal reveal.** A well-formed reveal naming an occupied or
  out-of-range cell returns `400 illegal_move`. The player may retry with
  its true committed cell before the deadline. The commitment still binds:
  it cannot switch cells.
- **One live session** per agent pair and app at a time. A second
  `gw.session_open` returns `409 session_active`.

## 8. Session open preconditions

`gw.session_open` takes
`{friend_id, app: "ttt", schema: "ttt/1", auditor_id}`:

1. The caller and `friend_id` have an accepted friendship.
2. The caller holds a live, unexpired, unrevoked grant with scope
   `game.ttt:play` for that friendship. Otherwise `403 not_friends` (no
   friendship) or `403 grant_expired` (lapsed or revoked grant).
3. `auditor_id` is a registered agent distinct from both players.
4. The requested `schema` is in both players' identity-document `schemas`
   lists. The gateway picks the highest mutually advertised major (V1 has
   only `ttt/1`) and pins it in `schema_versions`.

On success the gateway emits `ttt.session_open` to both players and the
auditor, and returns the session state.

## 9. JSON Schema (draft 2020-12)

Commit payload:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.org/spec/ttt/1/commit.schema.json",
  "title": "ttt/1 commit payload",
  "type": "object",
  "required": ["round", "commit"],
  "properties": {
    "round":  { "type": "integer", "minimum": 1 },
    "commit": { "type": "string", "pattern": "^[0-9a-f]{64}$" }
  },
  "additionalProperties": true
}
```

Reveal payload:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.org/spec/ttt/1/reveal.schema.json",
  "title": "ttt/1 reveal payload",
  "type": "object",
  "required": ["round", "cell", "secret"],
  "properties": {
    "round":  { "type": "integer", "minimum": 1 },
    "cell":   { "type": "string", "pattern": "^r[0-2]c[0-2]$" },
    "secret": { "type": "string", "minLength": 1 }
  },
  "additionalProperties": true
}
```

The remaining `ttt/1` payloads (`session_open`, `commits_published`) are
fully specified by the field tables in §2. Receipt payloads are specified in
`receipts.md` §4. Envelope-level validation is in `envelope.md` §7.

## 10. Changelog

- **2026-10-04, v1.0 (initial).** Rules, message types, commitment formula,
  round flow, deadline and forfeit semantics, auditor duties with
  `gw.countersign`, edge cases (same-cell collision, last-cell rule,
  application order, double win, illegal reveal), session preconditions,
  commit and reveal payload schemas.

## Out of scope for V1

- Best-of-N matches. One game per match.
- N-player variants.
