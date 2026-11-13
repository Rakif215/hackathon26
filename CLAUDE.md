# CLAUDE.md

Instructions for Claude Code (and other coding agents) working in this repo.

## Read first

- [PROJECT.md](PROJECT.md): what we're building, MVP scope and the judging lens. **Source of truth for scope.**
- [CONTEXT.md](CONTEXT.md): the hackathon briefs (Exasol Challenge 3 primary, BMD Challenge 1 secondary).
- [SETUP.md](SETUP.md): local environment, all of it verified working. Read before touching the database.

## Database

Exasol 2026.2.0 runs locally at `127.0.0.1:8563` (user `sys`). Connect from Python with
`src/hackathon26/db.py`, which resolves credentials on its own — don't hardcode a password anywhere.
The Exasol MCP server is registered in `.mcp.json`, so agents can explore the schema and run SQL directly.
`exasol status` tells you whether it's up; `exasol start` if not.

## Ground rules

- It's a 3-day hackathon (12–14 Nov 2026). Favour working end-to-end demos over polish. Ship the MVP list in
  PROJECT.md before any stretch item.
- **Trust is the judging criterion.** Every AI answer in the app must carry sources/evidence, an
  uncertainty or confidence signal, and a path to human (clinician) review. Don't build features that hide these.
- **Synthetic data only.** Never commit real patient data, secrets, `.env` files or AWS credentials.
- No dosing or diagnostic advice in app copy or prompts.

## Saving Claude tokens: delegate to Kiro

We have ~1000 Kiro credits (`kiro-cli` v3.3.0, installed at `~/.local/bin/kiro-cli`, logged in via GitHub).
Use Claude Code for planning, architecture, review and tricky debugging. Hand **bulk, well-specified work**
(boilerplate, CRUD, UI components, seed-data generators, tests) to Kiro:

```bash
kiro-cli chat --no-interactive --trust-workspace --trust-all-tools \
  --model claude-opus-5.5 --effort high "<precise task, files to touch, acceptance criteria>"
```

### Model picker (credit multipliers, verified 13 Nov 2026)

**Use the good models. We are optimising for a winning demo, not for credits.** 1000 credits is plenty for a
3-day hackathon, and a weak diff costs more in review time than it saves in credits.

| Model | Cost | Use for |
|---|---|---|
| `claude-opus-5.5` | **2.00x** | **Default.** Anything real: features, logic, architecture, UI. Cheaper than `claude-opus-5` (2.20x), so always prefer it. |
| `claude-sonnet-5.5` | 1.30x | Large mechanical diffs where Opus is overkill. |
| `claude-haiku-5.5` | 0.06x | Throwaway only: one-line greps, file listings, trivial renames. |

`kiro-cli chat --list-models` prints the full list. Default to `claude-opus-5.5` and add `--effort high`
(or `xhigh`) for hard problems.

### Working with Kiro

- Write tight prompts: name the files, the interface, and how to verify. Then review Kiro's diff with
  `git diff` before committing. Never commit a Kiro diff unread.
- `--trust-workspace` skips the "Trust this workspace?" prompt (needed for `--no-interactive`).
- `--trust-all-tools` lets it write files. Drop it (or use `--trust-tools=`) for read-only questions.
- `--effort low|medium|high|xhigh|max` tunes reasoning depth.
- `-r` resumes the last conversation in this directory; `--list-sessions` shows saved ones.
- Kiro reads `.kiro/steering/project.md`, which points back to these same docs, so both agents share context.

## AWS

- Bedrock can serve Claude models for the app itself (and can back Claude Code via `CLAUDE_CODE_USE_BEDROCK=1`).
- Keep the region and model ids in `.env` (gitignored). Document required variables in `.env.example`.
- AWS CLI **2.40.2 is installed** (`/opt/homebrew/bin/aws`). Sign in with `aws configure sso` or `aws configure`.

## Repo conventions

- Update PROJECT.md when scope changes and CONTEXT.md when we learn new facts (mentor feedback, data access).
- Small commits with clear messages. Branch off `main` for anything risky.
- GitHub: the repo is `Rakif215/hackathon26`. If a push 403s, check `gh auth status` — this machine has two
  accounts and the active one must be `Rakif215` (`gh auth switch --user Rakif215`).
- Disk space is tight on this machine. `npm cache clean --force`, `uv cache clean`, `brew cleanup -s --prune=all`
  free several GB if a tool complains.
