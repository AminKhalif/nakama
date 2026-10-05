# ADR: Ed25519 vendored (pure-Python implementation)

Date: 2026-10-04

## Context

The gateway's whole value is proving what crossed it: agents hold Ed25519
keypairs and sign every message; the gateway verifies signatures and
countersigns receipts (see PROPOSAL.md §6). We need Ed25519 keygen, sign, and
verify in the Python gateway and in the Python client library.

Python's standard library has **no Ed25519 support** (`hashlib` covers SHA-2;
`cryptography` is a third-party dependency, not stdlib). Vendors embedding
the client library in proprietary agents may not be able to take heavy or
copyleft dependencies, and the V1 demo must run with the smallest possible
install footprint.

## Decision

**Vendor a pure-Python Ed25519 implementation** (RFC 8032, ~200 lines,
curve25519 field arithmetic in plain Python) into `packages/python/gwclient/`,
behind a **swappable crypto interface**:

- All signing/verification code calls through an interface
  (`sign(sk, msg)`, `verify(pk, sig, msg)`, `keygen()`, `sk_to_pk(sk)`) —
  never the vendored code directly.
- The vendored implementation ships as the default backend so the library
  works out of the box with zero third-party dependencies.
- A `cryptography`-backed (or libsodium-backed) implementation can be
  dropped in by registering it as the backend — no caller changes.

The implementation **must** be validated against the **RFC 8032 test vectors**
(Appendix A: SIGN and VERIFY cases) as part of the conformance suite — a
pure-Python curve implementation that disagrees with the RFC vectors by one
bit is a silent, total break of the trust model.

## Alternatives considered

- **Require the `cryptography` package.** Trade-off: battle-tested and fast,
  but adds a native dependency (build toolchain needed on some platforms),
  and forces every embedding vendor to accept that dependency in their
  agent's dependency tree.
- **Pure-Python but inline in each module.** Trade-off: same crypto, but no
  swap point — upgrading to a hardware/HSM backend later would mean touching
  every call site.
- **ECDSA P-256 via `hashlib`/`ssl`.** Trade-off: stdlib-adjacent but awkward
  to use correctly from pure Python, and Ed25519 is the cleaner, modern
  choice for a new protocol (deterministic signatures, no RNG failure modes
  in signing).

## Consequences

- **Pro:** zero-dependency client library — install is `pip install` with no
  build step, which matters for vendors evaluating embedding.
- **Pro:** the swap interface means production operators can move to
  hardware-backed or FIPS-validated Ed25519 later without a protocol change
  (signatures are signatures on the wire either way).
- **Con:** pure-Python Ed25519 is slow (~ms per verify vs µs for native).
  Acceptable for V1 turn-based games (a handful of signatures per move), but
  it is *not* suitable for high-throughput paths — any future bulk-data
  plane must use the native backend.
- **Con:** a vendored crypto implementation is a maintenance burden: it must
  be clearly marked "do not hand-modify; validated against RFC 8032 vectors"
  and re-validated on every change. Side-channel resistance (constant-time
  field ops) is best-effort in pure Python — acceptable for V1 demo scope,
  documented as a limitation.
