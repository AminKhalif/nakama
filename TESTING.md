# TESTING.md — M5: human console usability test

> **DO NOT RUN AS PART OF THE BUILD.** This checklist is Milestone 5 and is
> reserved for Tajer (or a non-technical stand-in he designates). The build
> crew (M1–M4) proves the machinery; this test proves the *human experience*.

## Goal

A non-technical tester, given only the console URL and a short invite code,
completes the full friendship lifecycle **unassisted in under 10 minutes**:

1. **add-agent** — add a friend's agent from an invite code
2. **approve game** — approve the tic-tac-toe game install with its scopes
3. **watch a match** — find and watch a live match on the spectator feed
4. **revoke friendship** — revoke the friendship

...and the revocation **demonstrably freezes a live session** (not just
hides the UI — the game engine stops accepting moves from the revoked agent).

## Setup (for the person running the test)

- The gateway is running (hosted reference instance).
- Two demo agent identities exist: one for the tester, one for the "friend"
  (pre-created invite code handed to the tester on a card).
- A second person (or script) drives the friend's agent so a match can start.
- A stopwatch. Start it when the tester first opens the console.

## Numbered steps

1. **Open the console.** Tester opens the console URL on their phone. No login
   help beyond what's on screen.
2. **Add the agent.** Tester taps "Add agent" (or equivalent) and enters the
   invite code from the card. They should see an agent card: the friend agent's
   name, the owner's name, its vendor, and plain-language capabilities.
3. **Approve the friendship.** Tester approves the friend request, then reviews
   the scope sheet ("this agent may: play tic-tac-toe games; see game results")
   and accepts. Every grant shown must have an expiry date.
4. **Approve the game install.** Tester installs/approves the tic-tac-toe app
   for this friendship and approves the exact scope list
   (`game.ttt:play`).
5. **Watch a match.** Tester starts (or is told a match is starting) and finds
   the live spectator feed. The tester can narrate what's happening on the
   board from what they see.
6. **Revoke mid-match.** While the match is live, the tester taps
   "Unfriend"/"Revoke" for that friendship and confirms.
7. **Verify the freeze.** After revoking, the tester checks the match view:
   the session must show as **frozen** (not finished, not errored). Any further
   move attempts from the revoked agent must be rejected (visible in the
   session log or via a clear "session frozen" state).

## Exact pass criteria

- [ ] Steps 1–7 completed **without asking for help** (a single clarifying
      question about where to tap is a *note*, not a fail; needing someone to
      take the phone is a fail).
- [ ] Total elapsed time **< 10 minutes**, stopwatch from step 1 to step 7.
- [ ] After step 6, the live session is in a **frozen** state observable in
      the console (moves no longer accepted from the revoked agent; the other
      player is notified).
- [ ] The tester can state in their own words what the agent was allowed to
      do (the scope sheet was legible, not jargon).

## What to observe (notes for the observer, not the tester)

- Where did the tester hesitate or tap the wrong thing? Which label or icon
  was unclear?
- Did the invite-code step feel like "adding a friend" or like "configuring
  software"? (First is the target.)
- Did the scope sheet read as plain language? Did the expiry date register?
- Was the spectator feed obviously live (moves appearing) or did it look
  static?
- Was "revoke" easy to find under pressure mid-match? One tap + confirm is
  the bar.
- After revocation: did the frozen state communicate clearly, or did it look
  like a crash?

## Results table

| Date | Tester | Time taken | Pass / Fail | Notes |
|------|--------|------------|-------------|-------|
| _yyyy-mm-dd_ | _name_ | _mm:ss_ | _pass / fail_ | _hesitations, unclear labels, bugs_ |
| | | | | |

Copy a row per test run. Failing rows are as valuable as passing ones —
record exactly which step failed and what the tester said or did.
