# SPDX-License-Identifier: Apache-2.0
"""gwclient: embeddable Python client library for the agent-interop gateway.

Python 3.10+, signing via PyNaCl/libsodium. Implements the versioned specs: the
library speaks the protocol; it never reimplements the gateway
(enforcement lives in the gateway).
"""

from .crypto import generate_keypair, public_key_from_private, sign, verify
from .envelope import (BadEnvelope, BadSignature, EnvelopeError,
                       build_envelope, canonical, parse_envelope,
                       signing_bytes, verify_envelope)
from .commit import (commitment_input, make_commit, verify_commit)
from .identity import (IdentityError, document_signing_bytes,
                       verify_identity_document)
from .receipts import (GENESIS_PREV_HASH, ReceiptChainError, receipt_hash,
                       receipt_signing_bytes, verify_chain)
from .ttt import (IllegalMove, apply_move, cell_index, check_move,
                  check_win, is_full, new_board, outcome, parse_cell)
from .auditor import countersign
from .client import GWClient, GatewayError, ClientError

__version__ = "0.4.0"

__all__ = [
    "generate_keypair", "public_key_from_private", "sign", "verify",
    "BadEnvelope", "BadSignature", "EnvelopeError",
    "build_envelope", "canonical", "parse_envelope", "signing_bytes",
    "verify_envelope",
    "commitment_input", "make_commit", "verify_commit",
    "IdentityError", "document_signing_bytes", "verify_identity_document",
    "GENESIS_PREV_HASH", "ReceiptChainError", "receipt_hash",
    "receipt_signing_bytes", "verify_chain",
    "IllegalMove", "apply_move", "cell_index", "check_move", "check_win",
    "is_full", "new_board", "outcome", "parse_cell",
    "countersign",
    "GWClient", "GatewayError", "ClientError",
]
