# SPDX-License-Identifier: Apache-2.0
"""Commit/reveal helpers for the fairness primitive.

The commitment formula is LOCKED by the design (PROPOSAL.md Appendix B.6):

    commit = sha256_hex("gw/1|<session>|r<round>|<agent_id>|<cell>|<secret>")

The domain separator "gw/1" plus the bound session, round, and agent id
mean a commitment copied from another round, session, or player simply
fails verification — it cannot be replayed. The cell format is "r<row>c<col>"
(e.g. "r0c2"), zero-based.

Comparison of a recomputed commitment against a stored one uses
hmac.compare_digest (constant time) so verification does not leak the
expected hash through timing.
"""

import hashlib
import hmac

DOMAIN = "gw/1"


def commitment_input(session, round, agent_id, cell, secret):
    """The exact preimage string that is hashed. Exposed so other
    implementations (other languages, the independent receipt verifier)
    can reproduce it byte-for-byte."""
    return "%s|%s|r%s|%s|%s|%s" % (DOMAIN, session, round, agent_id,
                                   cell, secret)


def make_commit(session, round, agent_id, cell, secret):
    """Create a 64-hex-char commitment for a hidden move."""
    return hashlib.sha256(
        commitment_input(session, round, agent_id, cell,
                         secret).encode("utf-8")).hexdigest()


def verify_commit(commit_hex, session, round, agent_id, cell, secret):
    """Check a reveal against a commitment. Returns True/False.

    Every bound value (session, round, agent_id, cell) participates in
    the hash, so a reveal from the wrong context returns False.
    Comparison is constant-time.
    """
    if not isinstance(commit_hex, str):
        return False
    expected = make_commit(session, round, agent_id, cell, secret)
    return hmac.compare_digest(expected, commit_hex.lower())
