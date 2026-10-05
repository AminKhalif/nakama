# ADR: modular repo layout with swappable wire and storage

Date: 2026-10-04

## Context

Locked build directive (corrected 2026-10-04): modular, decoupled
architecture with **swappable wire and storage layers**, GitHub-transport
ready. The system must evolve through the iterations in PROPOSAL.md §1 —
hosted gateway → embeddable library → hybrid (logic migrates outward) →
developer self-host — without rewrites at each step.

## Decision

The repo is split into four bounded areas with explicit contracts between
them:

```
spec/            the protocol — versioned markdown + JSON Schemas + changelogs.
                 Human- and machine-readable. Changes here drive everything else.
packages/        implementations of the protocol:
  python/
    gateway/     the operable service (identity, friendship, sessions,
                 commit/reveal, receipts, deadlines, spectator feed, console).
    gwclient/    the embeddable client library (envelope sign/verify, schema
                 validation, commit/reveal helpers, receipt-chain verifier).
examples/        worked end-to-end usage:
  ttt-auditor/   player bots + auditor bot + console mock + spectator page +
                 independent post-game receipt verifier.
tests/           conformance suite (protocol behavior) + red-team checks
                 (adversarial behavior). Tests assert against spec/, never
                 against implementation internals.
docs/            research, decisions (this file), and operating docs
                 (TRANSPORT.md, TESTING.md).
```

**Boundary rules:**

- `spec/` is the source of truth. Code and tests conform to it; nothing
  else is a contract. A second implementer must be able to write a
  compatible client from `spec/` alone (M1 done-criterion).
- **Swappable wire:** the envelope/signing layer (A2A + signature extension)
  is isolated behind an interface in `gwclient`. If the transport ever
  changes (different RPC framing, future A2A message-signing), only that
  module changes.
- **Swappable storage:** the gateway's persistence (SQLite in V1) sits
  behind a repository interface. Moving to Postgres or another store is a
  new backend, not a gateway rewrite.
- `tests/` may only import public interfaces and read wire bytes — never
  reach into implementation internals. This is what makes the conformance
  suite meaningful across implementations.
- Iteration-3 migration (game rules move from gateway core into the app
  webhook, PROPOSAL.md §5) is pre-shaped by this layout: `examples/ttt-auditor`
  is App #1, and the gateway keeps identity/friendship/sessions/receipts/
  deadlines — the parts that stay.

## Alternatives considered

- **Monolith (one package, everything in-process).** Trade-off: fastest to
  write for V1, but Iteration 3's extraction and the anyone-can-run self-host
  story both require the boundaries anyway — building them later means
  untangling, which is where projects actually die.
- **Separate repos per component.** Trade-off: cleaner ownership at scale,
  but for a V1 built by one crew it multiplies versioning and transport
  overhead (four repos to push, four version numbers to keep in sync).
  Revisit if/when independent release cadences emerge.
- **Spec-as-code (schemas generated from implementation).** Trade-off:
  guarantees code/schema agreement, but inverts the contract — the spec
  should be implementable by *someone else*, which requires it to be written
  as a standalone document first.

## Consequences

- **Pro:** each milestone maps to a directory (M1→`spec/`, M2→`packages/`+
  `tests/`, M3→`examples/`), so progress is visible in the tree and
  reviewers can check one boundary at a time.
- **Pro:** the swappable wire/storage interfaces are the concrete mechanism
  behind "anyone can run" (SQLite default, Postgres later) and the
  vendored-Ed25519 swap story.
- **Con:** more scaffolding up front (interfaces, boundary discipline) than
  a monolith — the crew has to respect the boundaries or they rot into
  fiction. The `tests/`-only-public-interfaces rule is the enforcement
  mechanism; review should check it.
- **Con:** cross-cutting changes (e.g. a new envelope field) touch
  `spec/` + `packages/` + `tests/` in one change — accepted as the cost of
  a spec-first process.
