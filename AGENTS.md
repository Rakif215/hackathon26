# AGENTS.md

Instructions for coding agents (Kiro and others) working in this repo. Content is based on [CLAUDE.md](CLAUDE.md).

## Read first

- [PROJECT.md](PROJECT.md): what we're building, MVP scope and the judging lens. **Source of truth for scope.**
- [CONTEXT.md](CONTEXT.md): the hackathon briefs (Exasol Challenge 3 primary, BMD Challenge 1 secondary).
- [SETUP.md](SETUP.md): local environment, all of it verified working. Read before touching the database.

## Database

Exasol 2026.2.0 runs locally at `127.0.0.1:8563` (user `sys`). Connect from Python with
`src/hackathon26/db.py`, which resolves credentials on its own. Don't hardcode a password anywhere.
The Exasol MCP server is registered in `.mcp.json`, so agents can explore the schema and run SQL directly.
`exasol status` tells you whether it's up; `exasol start` if not.

## Ground rules

- It's a 3-day hackathon (12-14 Nov 2026). Favour working end-to-end demos over polish. Ship the MVP list in
  PROJECT.md before any stretch item.
- **Trust is the judging criterion.** Every AI answer in the app must carry sources/evidence, an
  uncertainty or confidence signal, and a path to human (clinician) review. Don't build features that hide these.
- **Synthetic data only.** Never commit real patient data, secrets, `.env` files or AWS credentials.
- No dosing or diagnostic advice in app copy or prompts.

## AWS (hackathon sandbox)

- Use the dedicated AWS CLI profile `hackathon`, region `us-west-2` (Oregon). It is an assumed role with
  temporary credentials, so expect them to expire during the event. The workshop allows only `us-west-2` and
  `eu-west-1`. Other regions return access-denied. We use `us-west-2` everywhere, including `.env`.
- Do not use other profiles or the `AWS_*` environment variables on a machine. They can point at unrelated accounts.
  Run AWS commands in a subshell that unsets `AWS_*` variables and points `AWS_CONFIG_FILE` and
  `AWS_SHARED_CREDENTIALS_FILE` at the hackathon files. Each developer's file locations and the sandbox account ID
  are in the local, gitignored `.kiro/steering/aws-context.md`. Create it from your own setup if it is missing.
- Before any command that changes resources, run `aws sts get-caller-identity --profile hackathon` and confirm
  the account is the sandbox account.
- Bedrock serves the Claude models for the app. Other sandbox services: Knowledge Bases and Guardrails,
  Bedrock AgentCore, and a serverless backend (Lambda, API Gateway, DynamoDB, S3).
- Keep the region and model ids in `.env` (gitignored). Document required variables in `.env.example`.
- Never print or commit credential values.

## Repo conventions

- Update PROJECT.md when scope changes and CONTEXT.md when we learn new facts (mentor feedback, data access).
- Small commits with clear messages. Branch off `main` for anything risky.
- GitHub: the repo is `Rakif215/hackathon26`.
