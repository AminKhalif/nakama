# SPDX-License-Identifier: Apache-2.0
"""Helpers for the auditor (broker) role.

The auditor is untrusted by design: it never sees moves before reveal
(only commitments), it cannot change a committed move (hash binding),
and it cannot lie about the result undetectably (the receipt chain is
replayable by anyone). These helpers cover the two things the auditor
does sign off on: that a move is legal, and countersigning receipts.

Per spec/ttt-v1.md section 6 the auditor signs the canonical receipt
bytes with the signature fields removed, then submits the signature via
gw.countersign (envelope.md section 3). GWClient.countersign performs
the submission; the helper below only produces the signature value.
"""

from . import crypto
from . import receipts as receipts_mod
from .ttt import (IllegalMove, cell_index, check_move,  # noqa: F401
                  parse_cell)


def countersign(receipt, auditor_private_key_hex):
    """Compute the auditor's countersignature for a receipt dict (the
    shape gw.receipts returns).

    Signs the canonical receipt bytes with gw_sig and auditor_sig
    removed (receipts.md section 1) and returns the signature as an
    "ed25519:<128 hex>" string, ready for gw.countersign's
    auditor_sig field.
    """
    sig = crypto.sign(auditor_private_key_hex,
                      receipts_mod.receipt_signing_bytes(receipt))
    return "ed25519:" + sig.hex()
