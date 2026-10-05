#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Independent receipt-chain verifier for the ttt-auditor demo.

Reads ONLY receipts plus the two public keys and runs the receipts.md
section 3 chain algorithm via gwclient.verify_chain. Imports gwclient and
the stdlib -- never gateway code, so this is a genuine second opinion on
what the gateway and auditor attested.

Usage:
    python3 verify_receipts.py --base-url http://127.0.0.1:PORT \\
        --auditor-pubkey ed25519:<64 hex> sess_xxx [sess_yyy ...]

The gateway public key comes from the gateway's Agent Card
(/.well-known/agent-card.json). The auditor public key is passed
out-of-band (it is the auditor's identity key; the demo prints it).

Exit 0: every match's chain is VALID. Exit non-zero: at least one chain
failed; the failing receipt is named in the output.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "packages", "python"))

from gwclient import GWClient, ReceiptChainError, verify_chain  # noqa: E402


def verify_session(client, gw_pubkey, auditor_pubkey, session):
    """Returns (ok, detail). Raises on transport failure."""
    chain = client.receipts(session)
    verify_chain(chain, gw_pubkey, auditor_pubkey)
    rounds = [r for r in chain if "rounds_played" not in r]
    game = [r for r in chain if "rounds_played" in r][0]
    return True, ("%d round receipts + game receipt, result=%s"
                  % (len(rounds), game["result"]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="independently verify ttt receipt chains")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--auditor-pubkey", required=True,
                    help="ed25519:<64 hex> auditor identity key")
    ap.add_argument("sessions", nargs="+", help="session ids to verify")
    args = ap.parse_args(argv)

    client = GWClient.new(args.base_url, timeout=15)
    try:
        gw_pubkey = client.agent_card()["gwPubkey"]
    except Exception as exc:
        print("cannot fetch the gateway Agent Card: %s" % exc, flush=True)
        return 2
    print("gateway pubkey: %s" % gw_pubkey, flush=True)
    print("auditor pubkey: %s" % args.auditor_pubkey, flush=True)

    failed = 0
    for session in args.sessions:
        try:
            _ok, detail = verify_session(client, gw_pubkey,
                                         args.auditor_pubkey, session)
        except ReceiptChainError as exc:
            failed += 1
            print("FAIL %s: INVALID -- %s" % (session, exc), flush=True)
        except Exception as exc:  # transport etc.
            failed += 1
            print("FAIL %s: could not verify (%s: %s)"
                  % (session, type(exc).__name__, exc), flush=True)
        else:
            print("OK   %s: VALID -- %s" % (session, detail), flush=True)

    print("%d/%d chains valid" % (len(args.sessions) - failed,
                                  len(args.sessions)), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
