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

We have ~1000 Kiro credits. Use Claude Code for planning, architecture, review and tricky debugging.
Hand **bulk, well-specified work** (boilerplate, CRUD, UI components, seed-data generators, tests) to Kiro:

```bash
kiro-cli chat --no-interactive --trust-all-tools --model <model-id> "<precise task, files to touch, acceptance criteria>"
```

- Run `kiro-cli chat --help` and `kiro-cli chat` → `/model` to confirm the exact flags and model ids available
  on our plan, then record them here.
- Write tight prompts: name the files, the interface, and how to verify. Then review Kiro's diff with `git diff`
  before committing.
- Kiro also reads `.kiro/steering/`, which points back to these same docs, so both agents share context.

## AWS

- Bedrock can serve Claude models for the app itself (and can back Claude Code via `CLAUDE_CODE_USE_BEDROCK=1`).
- Keep the region and model ids in `.env` (gitignored). Document required variables in `.env.example`.

## Repo conventions

- Update PROJECT.md when scope changes and CONTEXT.md when we learn new facts (mentor feedback, data access).
- Small commits with clear messages. Branch off `main` for anything risky.
