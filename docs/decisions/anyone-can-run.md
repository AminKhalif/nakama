# ADR: anyone-can-run operator model

Date: 2026-10-04

## Context

The gateway is the single choke point that enforces fairness: it holds the
identity registry, friend graph, sessions, deadlines, and the receipt chain.
Whoever operates a gateway instance is trusted by the humans and agents that
use it. The question: is the operator *us* (one hosted service), or can
anyone run one?

Locked decision: **anyone can run a gateway**. The hosted instance is
the reference default, not the only option. But end users don't self-host
(design constraint) — self-hosting is for developers and vendors evaluating
embedding, not for the family-finance product UX.

## Decision

**Anyone-can-run, with a documented reference path:**

- The gateway runs from the repo with a documented setup: SQLite storage,
  a Dockerfile, one-command local start. No exotic infrastructure, no
  paid dependencies required to get a working instance.
- The hosted instance is the **reference default**: the demo, the docs,
  and the client library all point at it. "Reference default" means it is
  the instance new users land on and the one our tests run against — not
  that it is the only permitted instance.
- **Federation hooks from day one:** identity documents are signed and
  portable (verifiable offline with the issuing gateway's public key),
  receipt chains are exportable (anyone can replay a finished game from
  receipts alone). These make it *possible* for independent operators to
  exist without breaking the trust story. Full cross-operator federation
  (registry gossip, cross-instance disputes) is explicitly out of V1 scope.

## Alternatives considered

- **Hosted-only (we are the sole operator).** Trade-off: simplest ops, one
  revocation list, one receipt chain — but every developer objection
  ("but I can't run your cloud") becomes a blocker for app development,
  and vendor adoption stalls.
- **Federated from day one (NANDA-quilt-style registries).** Trade-off:
  ideologically aligned with decentralization, but pays ~5x V1 complexity
  (key discovery across operators, CRDT sync, cross-instance dispute
  handling) before one working game exists. Rejected per PROPOSAL.md §7.
- **Fully peer-to-peer / crypto-decentralized.** Trade-off: no operator to
  trust, but surrenders the single enforcement point our fairness story
  depends on, and key-management UX no non-technical user will survive.
  Never-by-default per PROPOSAL.md §7.

## Consequences

- **Pro:** the self-host path removes the "run your cloud" objection for
  developers and vendors, while the reference default keeps the end-user
  story simple (nobody self-hosts the family product).
- **Pro:** portable identities + exportable receipts mean operator lock-in
  is a policy choice, not an architectural one — a future federation layer
  can be built on formats that already exist.
- **Con:** independent operators are mutually untrusted by default — two
  gateways cannot jointly run a game until federation is designed. V1 games
  happen on *one* gateway instance at a time. This must be stated plainly in
  user-facing docs so nobody assumes cross-instance play works.
- **Con:** the reference default is still a single point of trust and
  censorship for its users. Mitigation is transparency (exportable receipts,
  open source), not denial.
