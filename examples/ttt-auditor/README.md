# SPDX-License-Identifier: Apache-2.0
# Tic-tac-toe + auditor: the V1 reference app

Two agents play tic-tac-toe through the gateway with a third agent as
auditor, per `spec/ttt-v1.md`. Every round uses simultaneous
commit/reveal (neither side sees the other's move before committing);
every round and game produces a hash-chained receipt signed by the
gateway **and** countersigned by the auditor. Anyone can verify the chain
offline afterward.

## Layout

- `brains/` — pluggable decision engines. The `Brain` interface is one
  method: `choose_move(board, me) -> "r<row>c<col>"`, where `board` is 9
  cells (`"a"`/`"b"`/`None`, row-major) and `me` is `"a"` or `"b"`.
  - `brains/scripted.py` — deterministic strategies (`CenterFirst`,
    `Scripted(priority_list)`, `RandomSeeded(seed)`). **The default.**
    The demo and the tests never touch the network.
  - `brains/llm.py` — OpenAI-compatible chat-completions client (stdlib
    only), aimed at NVIDIA NIM. Falls back to a scripted brain on **any**
    failure (no key, network error, illegal output) and never logs the key.
- `player.py` — the full player agent: keypair, `gw.register`,
  `gw.friend_request`, waits for the human's console approval, opens the
  match, and plays every round through commit/reveal with its Brain.
- `auditor_bot.py` — the referee agent. **Deliberately not LLM-driven:**
  a referee must be deterministic and replayable, otherwise nobody could
  re-check its attestation. It verifies each round receipt (commitments
  match what was published, reveals are legal, board math and outcome
  recompute) and countersigns via `gw.countersign`. It refuses anything it
  cannot verify.
- `run_demo.py` — zero-human-action demo: spawns a gateway, registers
  Amber, Blaise and Referee, approves the friendship through the operator
  console, plays 3 full matches (side-a win, side-b win, **draw** via the
  last-cell rule), verifies every receipt chain, prints results.
  Exit non-zero on any failure.
- `verify_receipts.py` — **independent** verifier: fetches the gateway
  Agent Card, pulls `gw.receipts`, runs `gwclient.verify_chain` on every
  match. Imports `gwclient` + stdlib only — never gateway code.
  Exit 0 = all chains valid, naming the failing receipt otherwise.
- `tests/test_brains.py` — brain contracts, LLM fallback paths, and an
  offline simulation proving the three scripted layouts yield exactly
  a-win, b-win, and draw.

## Run the gateway (by hand)

```bash
cd ~/workspace/agent-interop/packages/python
GW_CONSOLE_TOKEN=pick-a-token python3 -m gateway.server \
  --port 8080 --db /tmp/gw.db --host 127.0.0.1
```

Spectator page for a session: `http://127.0.0.1:8080/g/<session_id>`.
Operator console: `http://127.0.0.1:8080/console`.

## Run the demo (3 matches, all attested and verified)

```bash
cd ~/workspace/agent-interop/examples/ttt-auditor
python3 run_demo.py
```

Spawns its own gateway on an ephemeral port with a temp db — nothing to
set up. Expected: match 1 result `a`, match 2 result `b`, match 3 result
`draw`, every chain `VALID`. Any deviation exits non-zero.

## Run the independent verifier

```bash
cd ~/workspace/agent-interop/examples/ttt-auditor
python3 verify_receipts.py --base-url http://127.0.0.1:<PORT> \
  --auditor-pubkey ed25519:<auditor hex> sess_<id> [sess_<id> ...]
```

`run_demo.py` prints session ids, the gateway port, and the auditor's
public key — everything the verifier needs:
`--auditor-pubkey ed25519:<hex from the demo output>`.
Exit 0: every chain valid. Otherwise the failing receipt is named.

## Enable the LLM brain (NVIDIA NIM)

```bash
export NVIDIA_API_KEY="nvapi-..."        # from build.nvidia.com (free signup)
# optional overrides:
export NVIDIA_API_BASE="https://integrator.api.nvidia.com/v1"
export NVIDIA_MODEL="nousresearch/hermes-3-llama-3.1-70b"   # default; any
                                                            # OpenAI-compatible
                                                            # model id works
cd ~/workspace/agent-interop/examples/ttt-auditor
python3 run_demo.py --brains llm
```

Without `NVIDIA_API_KEY` the brain prints one clear note and plays
scripted — the demo never stalls on the LLM. The key is sent only as an
`Authorization: Bearer` header to `NVIDIA_API_BASE` and never logged,
printed, or persisted. (The demo's scripted outcomes are asserted only in
`--brains scripted` mode; LLM play is not asserted — it is a live model.)

Single player with the LLM brain against a running gateway:

```bash
python3 player.py --base-url http://127.0.0.1:8080 --name Amber \
  --brain llm --peer <opponent_agent_id> --auditor <auditor_agent_id>
```

Brain specs for `--brain`: `center`, `seed:N`, `list:r0c0,r1c1,...`, `llm`.

## Tests

```bash
cd ~/workspace/agent-interop/examples/ttt-auditor
python3 -m unittest discover -s tests
```
