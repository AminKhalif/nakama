# TRANSPORT.md — pushing this repo to GitHub (Tajer does this himself)

This repo is **GitHub-ready**: the remote is created by *you*, on *your* GitHub
account, and you push the code there yourself. Nobody on the build crew touches
remotes, tokens, or GitHub accounts.

## Step 0 — prerequisites

- A [github.com](https://github.com) account, signed in.
- Git installed. Check: `git --version`

## Step 1 — initialize the local repo

Run these in `~/workspace/agent-interop/`:

```bash
cd ~/workspace/agent-interop
git init -b main
git add -A
```

Sanity check before committing — `git status` should list exactly the files you
expect: `LICENSE`, `README.md`, `PROPOSAL.md`, `TRANSPORT.md`, `TESTING.md`,
`.gitignore`, `docs/`, `spec/`, `packages/`, `examples/`, `tests/`. You should
**not** see `.env`, `*.pem`, `*.key`, `*.db`, `*.log`, or any `secrets*` files.
If you do, STOP and remove them (check `.gitignore` first — it should be
catching all of these).

## Step 2 — first commit

```bash
git commit -m "Initial commit: agent-interop gateway V1"
```

## Step 3 — create the repo on GitHub (web UI, you do this)

1. Go to https://github.com/new (signed in as yourself).
2. Repository name: `agent-interop` (or whatever you prefer).
3. Visibility: **Public** recommended — this project is an open interop
   standard; Apache-2.0 licensing only matters if people can read it.
4. Do **NOT** check "Add a README file", "Add .gitignore", or "Choose a
   license" — this repo already has all three, and GitHub adding its own
   would create a conflict.
5. Click **Create repository**. GitHub shows you the repo URL, e.g.
   `https://github.com/YOUR-USERNAME/agent-interop.git`.

## Step 4 — link and push

```bash
git remote add origin https://github.com/YOUR-USERNAME/agent-interop.git
git push -u origin main
```

Replace `YOUR-USERNAME` with your actual GitHub username. That's it — the
code is on GitHub.

## Authenticating without pasting tokens in chat

**NEVER paste an access token into chat, a message, or a file in this repo.**
Anyone who can read it can push as you. Two safe paths:

- **Preferred: GitHub CLI.**
  ```bash
  gh auth login
  ```
  Follow the interactive prompt (it opens a browser flow). After that,
  `git push` works with no token handling on your side.
- **Or: fine-grained personal access token (PAT).** Create it at
  https://github.com/settings/personal-access-tokens/new — scope it to the
  one repo, give it only "Contents: read and write". When Git prompts for a
  password, paste the token. Save it in your system's credential store
  (macOS Keychain / Windows Credential Manager / Linux `git credential`
  helper), not in a note or chat. Regenerate it if it ever touches a
  chat log.

## What NOT to do

- Do not let an agent or build script create the GitHub repo for you — the
  remote belongs to you.
- Do not paste a token anywhere an agent can see it (chat, shared files,
  screenshots).
- Do not commit `.env`, keys, or `*.db` files — they're in `.gitignore`,
  and Step 1's sanity check should confirm they're absent.
