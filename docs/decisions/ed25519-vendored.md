# ADR: Ed25519 implementation

## Decision

Use PyNaCl/libsodium for key generation, signing, verification, and public-key
subgroup validation. The gateway wraps the SDK backend to preserve its existing
hex-signature API; the SDK returns detached signature bytes.

The original implementation duplicated pure-Python curve arithmetic in the client
and gateway. Neither duplication nor zero-dependency installation justifies
maintaining secret-key arithmetic inside this project. PyNaCl is now a required
runtime dependency, installed through the package metadata.

The wire format is unchanged: a 32-byte private seed, 32-byte public key, and
64-byte detached Ed25519 signature. RFC 8032 vectors and the existing conformance
and adversarial suites verify compatibility. Registered keys must pass libsodium's
main-subgroup point validation; a syntactically valid hex string is insufficient.

## References

- [PyNaCl signing API](https://pynacl.readthedocs.io/en/latest/signing/)
- [libsodium point validation](https://doc.libsodium.org/advanced/point-arithmetic)
