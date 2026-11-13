# CLAUDE.md

Instructions for Claude Code (and other coding agents) working in this repo.

## Read first

- [PROJECT.md](PROJECT.md): what we're building, MVP scope and the judging lens. **Source of truth for scope.**
- [CONTEXT.md](CONTEXT.md): the hackathon briefs (Exasol Challenge 3 primary, BMD Challenge 1 secondary).

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
  --model claude-opus-5.5 "<precise task, files to touch, acceptance criteria>"
```

### Model picker (credit multipliers, verified 13 Nov 2026)

| Model | Cost | Use for |
|---|---|---|
| `claude-haiku-5.5` | **0.06x** | Bulk boilerplate, seed data, repetitive edits. Default workhorse. |
| `auto` | 1.00x | When unsure; Kiro picks per task. |
| `claude-sonnet-5.5` | 1.30x | Normal feature work. |
| `claude-opus-5.5` | 2.00x | Hard logic, architecture. Cheaper than `claude-opus-5` (2.20x), so prefer it. |

`kiro-cli chat --list-models` prints the full list. Haiku 5.5 at 0.06x is ~33x cheaper than Opus 5.5 — reach
for it first and only escalate when the output isn't good enough.

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
- AWS CLI is **not installed yet**. Install with `brew install awscli`, then `aws configure` / `aws configure sso`.

## Repo conventions

- Update PROJECT.md when scope changes and CONTEXT.md when we learn new facts (mentor feedback, data access).
- Small commits with clear messages. Branch off `main` for anything risky.
- GitHub: the repo is `Rakif215/hackathon26`. If a push 403s, check `gh auth status` — this machine has two
  accounts and the active one must be `Rakif215` (`gh auth switch --user Rakif215`).
- Disk space is tight on this machine. `npm cache clean --force`, `uv cache clean`, `brew cleanup -s --prune=all`
  free several GB if a tool complains.
