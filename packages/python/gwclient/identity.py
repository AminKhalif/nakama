# SPDX-License-Identifier: Apache-2.0
"""Identity documents (spec/identity.md).

The gateway signs the document at registration. Anyone holding the
gateway public key (from its Agent Card) can verify the document
offline: the signature covers the canonical bytes of the document with
gw_sig removed (canonicalization per envelope.md section 2).
"""

import re

from . import crypto
from .envelope import canonical

REQUIRED_FIELDS = ("id", "agent_name", "owner_display_name", "vendor",
                   "pubkey", "endpoints", "capabilities", "schemas",
                   "accepts", "certification", "issued_at", "expires_at",
                   "did", "gw_sig")

_ID_RE = re.compile(r"^agent_[0-9a-f]+$")
_PUBKEY_RE = re.compile(r"^ed25519:[0-9a-f]{64}$")
_SIG_RE = re.compile(r"^ed25519:[0-9a-f]{128}$")


class IdentityError(ValueError):
    """An identity document is malformed or its signature is invalid."""


def document_signing_bytes(document):
    """The bytes gw_sig covers: canonical JSON with gw_sig removed."""
    unsigned = {k: v for k, v in document.items() if k != "gw_sig"}
    return canonical(unsigned)


def verify_identity_document(document, gateway_pubkey_hex):
    """Check the document's shape (spec/identity.md section 7) and its
    gw_sig. gateway_pubkey_hex is "ed25519:<64 hex>" or bare 64 hex.
    Returns the document on success; raises IdentityError otherwise."""
    if not isinstance(document, dict):
        raise IdentityError("identity document must be a JSON object")
    for field in REQUIRED_FIELDS:
        if field not in document:
            raise IdentityError("identity document missing %r" % (field,))
    if not _ID_RE.match(document["id"]):
        raise IdentityError("id %r must be 'agent_' plus a hex suffix"
                            % (document["id"],))
    name = document["agent_name"]
    if not isinstance(name, str) or not 1 <= len(name) <= 40:
        raise IdentityError("agent_name must be 1..40 chars")
    if not _PUBKEY_RE.match(document["pubkey"] or ""):
        raise IdentityError("pubkey must be 'ed25519:' + 64 hex chars")
    if document["did"] is not None:
        raise IdentityError("did must be null in V1")
    if not isinstance(document["endpoints"], dict):
        raise IdentityError("endpoints must be an object")
    for field in ("capabilities", "schemas", "accepts"):
        if not isinstance(document[field], list):
            raise IdentityError("%s must be an array" % (field,))
    if not isinstance(document["certification"], dict):
        raise IdentityError("certification must be an object")
    sig = document["gw_sig"]
    if not isinstance(sig, str) or not _SIG_RE.match(sig):
        raise IdentityError("gw_sig must be 'ed25519:' + 128 hex chars")
    key_hex = gateway_pubkey_hex
    if key_hex.startswith("ed25519:"):
        key_hex = key_hex[len("ed25519:"):]
    try:
        if len(bytes.fromhex(key_hex)) != 32:
            raise IdentityError("gateway public key is not 32 bytes")
    except (ValueError, TypeError):
        raise IdentityError("gateway public key is not hex")
    if not crypto.verify(key_hex, document_signing_bytes(document),
                         bytes.fromhex(sig[len("ed25519:"):])):
        raise IdentityError("gw_sig is not a valid gateway signature")
    return document
