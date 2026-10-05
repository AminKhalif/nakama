# SPDX-License-Identifier: Apache-2.0
"""Pluggable agent brains for the tic-tac-toe demo.

A Brain is the *only* decision-making part of a player agent. Everything
else (keypair, registration, friendship, commit/reveal, receipt handling)
lives in player.py and is identical no matter which brain is plugged in.
That is the interop point: two different vendors' decision engines can
play each other because the wire protocol, not the brain, is shared.

Interface::

    class Brain:
        name = "human-readable name"
        def choose_move(self, board, me):
            '''board: 9-list of "a"/"b"/None, row-major ("r0c0" is index 0).
               me: "a" (X, first) or "b" (O, second).
               Return one legal cell like "r1c2".'''

The board the brain sees contains only *revealed* marks, exactly what the
gateway reports. The brain never sees the opponent's unrevealed move: the
simultaneous commit/reveal (spec/ttt-v1.md section 3) keeps it hidden.

Available brains:
- brains.scripted.CenterFirst / Scripted / RandomSeeded: deterministic,
  zero-network. This is the default for the demo and the integration
  tests: no external API is ever touched.
- brains.llm.LLMBrain: OpenAI-compatible chat-completions client (stdlib
  only) aimed at NVIDIA NIM; falls back to a scripted brain on ANY
  failure and never needs a key to run.
"""

from .scripted import CenterFirst, RandomSeeded, Scripted, ScriptedBrain

__all__ = ["CenterFirst", "RandomSeeded", "Scripted", "ScriptedBrain",
           "parse_brain_spec"]


def parse_brain_spec(spec, llm_class=None):
    """'center' | 'seed:N' | 'list:r0c0,r1c1,...' | 'llm' -> a Brain."""
    spec = (spec or "center").strip()
    if spec == "center":
        return CenterFirst()
    if spec.startswith("seed:"):
        return RandomSeeded(int(spec.split(":", 1)[1]))
    if spec.startswith("list:"):
        cells = [c.strip() for c in spec.split(":", 1)[1].split(",")
                 if c.strip()]
        return Scripted(cells, name="scripted-list")
    if spec == "llm":
        if llm_class is None:
            from .llm import LLMBrain as llm_class
        return llm_class()
    raise ValueError("unknown brain spec %r: want center | seed:N | "
                     "list:... | llm" % (spec,))
