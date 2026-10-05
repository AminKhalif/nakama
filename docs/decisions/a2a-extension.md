# ADR: per-message Ed25519 signatures as an A2A extension

Date: 2026-10-04

## Context

Locked decision: the wire protocol is Google's Agent2Agent (A2A) JSON-RPC
v1.0.1. The research found A2A signs **Agent Cards only** — the messages
themselves are unsigned [S]. The gateway's anti-scam story (§6 of PROPOSAL.md)
depends on non-repudiation *at the message level*: commit-reveal bindings,
auditor countersigning, and hash-chained receipts are all meaningless if a
message can be forged or repudiated after the fact.

## Decision

Add **per-message Ed25519 signatures as a documented, cleanly-separable
A2A extension** (`spec/a2a-extension.md`):

- Every envelope carries `sig`: an Ed25519 signature over the canonicalized
  message bytes, in addition to the sender's agent id.
- The extension is **additive**: a pure-A2A client that ignores unknown
  envelope fields can still *exchange* messages with the gateway
  (maximal A2A compatibility per the locked decision).
- Messages the gateway forwards are only forwarded **after** signature
  verification; unsigned or mis-signed messages are rejected with a typed
  error and never reach the counterparty or the auditor.
- The extension lives in its own spec file with its own version marker
  (`gw/1` envelope + signature extension), so it can evolve or be replaced
  without touching the A2A base.

## Alternatives considered

- **Pure A2A, no extension (trust the transport, e.g. mTLS/bearer tokens).**
  Trade-off: this is exactly the bridge's bearer-only model, which the
  research showed is insufficient — a leaked transport token would let an
  attacker forge another agent's moves, and there would be no signed
  evidence of what crossed the gateway. Rejected: it guts the receipt story.
- **Replace A2A with our own protocol.** Trade-off: full control, but we
  lose interop with the A2A ecosystem — the point of the project is that
  *other vendors' agents* can talk to ours with minimal work.
- **Sign only receipts, not every message.** Trade-off: cheaper, but
  commit-reveal fairness then rests on gateway assertions rather than
  agent non-repudiation — the gateway could be accused of inventing commits,
  and there would be no cryptographic defense.

## Consequences

- **Pro:** the extension fills exactly the gap the research identified
  (A2A signs cards, not messages), and because it's separable, a future
  A2A version that adds message signing could absorb it.
- **Pro:** maximal A2A compatibility is preserved — the extension degrades
  to "unsigned A2A message" for clients that don't implement it, and the
  gateway's policy (reject unsigned in V1 sessions) is a configuration
  choice, not a wire break.
- **Con:** canonicalization rules for "what bytes get signed" are a new
  spec surface — they must be pinned down exactly (JSON canonical form,
  field order) or two implementations will produce different signatures
  over identical messages. This is M1 spec work, not optional.
- **Con:** signing every message adds per-message crypto cost (see the
  vendored-Ed25519 ADR); fine for turn-based V1, must be revisited for
  any high-frequency message types.
