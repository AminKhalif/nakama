# SPDX-License-Identifier: Apache-2.0
"""LLM brain: one move per round from an OpenAI-compatible
chat-completions endpoint (stdlib urllib only).

Target: NVIDIA NIM at build.nvidia.com (free API key), whose endpoint is
OpenAI-compatible. Env config:

- NVIDIA_API_KEY   the key. Absent -> clear message, scripted fallback.
- NVIDIA_API_BASE  default "https://integrator.api.nvidia.com/v1"
- NVIDIA_MODEL     default "nousresearch/hermes-3-llama-3.1-70b"
                   (Nous Hermes NIM; override freely, e.g. another vendor)

Contract (the cross-vendor interop proof): the brain is swappable. The
rest of the player (keypair, registration, commit/reveal, receipts) is
byte-identical whether the move came from a script or an LLM.

Safety: the key is read from the environment at call time into a local
variable, sent only as an Authorization: Bearer header to the configured
base URL, and never logged, printed, persisted, or stored on the object.
On ANY failure (no key, network error, bad JSON, illegal move text) the
brain falls back to the scripted brain, so a game can never stall on the
LLM. The demo and the integration tests never touch this path.
"""

import json
import os
import re
import urllib.error
import urllib.request

from .scripted import CenterFirst

DEFAULT_API_BASE = "https://integrator.api.nvidia.com/v1"
DEFAULT_MODEL = "nousresearch/hermes-3-llama-3.1-70b"

_CELL_RE = re.compile(r"r([0-2])c([0-2])")

_SYSTEM = (
    "You are playing tic-tac-toe on a 3x3 board. "
    "Cells are named r<row>c<col> with rows and cols 0 to 2, "
    "for example r0c2 is the top-right cell. "
    "You must reply with ONLY the cell of your move, like r1c2. "
    "No explanation, no punctuation, just the cell."
)


def _board_text(board, me):
    mark = {"a": "X", "b": "O", None: "."}
    rows = []
    for r in range(3):
        rows.append(" ".join(mark[board[r * 3 + c]] for c in range(3)))
    side = "X (first)" if me == "a" else "O (second)"
    legal = ["r%dc%d" % (i // 3, i % 3)
             for i, c in enumerate(board) if c is None]
    return ("You are %s.\nBoard:\n%s\nLegal moves: %s\nYour move:"
            % (side, "\n".join(rows), ", ".join(legal)))


class LLMBrain:
    """choose_move via chat-completions, scripted fallback on any fault."""

    def __init__(self, fallback=None, model=None, api_base=None,
                 timeout=25):
        self.fallback = fallback or CenterFirst()
        self.model = model or os.environ.get("NVIDIA_MODEL",
                                             DEFAULT_MODEL)
        self.api_base = (api_base or os.environ.get("NVIDIA_API_BASE",
                                                    DEFAULT_API_BASE)).rstrip("/")
        self.timeout = timeout
        self.name = "llm(%s)" % self.model
        self._warned = False

    @staticmethod
    def available():
        """True when a key is configured (the only thing needed)."""
        return bool(os.environ.get("NVIDIA_API_KEY", "").strip())

    def _note(self, text):
        if not self._warned:
            self._warned = True
            print("[llm-brain] %s -- using scripted fallback" % text,
                  flush=True)

    def choose_move(self, board, me):
        api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
        if not api_key:
            self._note("NVIDIA_API_KEY is not set")
            return self.fallback.choose_move(board, me)
        try:
            cell = self._query(board, me, api_key)
        except Exception as exc:  # network, JSON, HTTP errors: all -> fallback
            self._note("LLM call failed (%s: %s)"
                       % (type(exc).__name__, _short(str(exc))))
            return self.fallback.choose_move(board, me)
        legal = {"r%dc%d" % (i // 3, i % 3)
                 for i, c in enumerate(board) if c is None}
        if cell not in legal:
            self._note("LLM returned illegal move %r" % (cell,))
            return self.fallback.choose_move(board, me)
        return cell

    def _query(self, board, me, api_key):
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _board_text(board, me)},
            ],
            "temperature": 0.2,
            "max_tokens": 16,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.api_base + "/chat/completions",
            data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + api_key,
                     "User-Agent": "ttt-auditor-demo/1"})
        try:
            with urllib.request.urlopen(req,
                                        timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Read the error body for the note, but never echo headers.
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except OSError:
                detail = ""
            raise RuntimeError("HTTP %s %s" % (exc.code, detail.strip()))
        text = (payload.get("choices") or [{}])[0].get("message", {}) \
            .get("content", "")
        match = _CELL_RE.search(text or "")
        if not match:
            raise RuntimeError("no cell found in model output %r"
                               % (text[:80],))
        return "r%sc%s" % (match.group(1), match.group(2))


def _short(text, limit=120):
    """One-line, length-capped error text for the fallback note. The API
    key never appears here: it is only ever sent in a header."""
    return " ".join(text.split())[:limit]
