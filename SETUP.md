# SETUP.md — Local environment

Everything below is **installed and verified working** on the primary dev machine (macOS 27, Apple Silicon).
Teammates: follow this to get the same setup.

## 1. Exasol Personal (the database)

We use the **Exasol Personal launcher**, not the `exasol/docker-db` image. `docker-db` is x86-64 only and
won't run natively on Apple Silicon. The launcher runs the database in a managed Podman VM.

```bash
curl https://downloads.exasol.com/exasol-personal/installer.sh | sh
```

Then install the local deployment. **Pass `--data-size-gb`** — the default VM disk is 100 GB:

```bash
exasol install local --auto-approve --data-size-gb 20 --memory-mb 4096 --cpu-count 2
```

Actual footprint once installed: **~1.6 GB** on disk. The VM takes 4 GB RAM while running.

Verify:

```bash
exasol status                 # -> Status: database_ready
exasol connect -c "SELECT 1;" # -> returns 1
exasol info                   # connection details
```

Lifecycle: `exasol stop` / `exasol start` / `exasol destroy`.

**Installed version: Exasol 2026.2.0-nano.8** · endpoint `127.0.0.1:8563` · user `sys`.

### Credentials

The launcher generates a random `sys` password per deployment and writes it to
`~/.exasol/personal/deployments/default/secrets.json` (key `dbPassword`). It is **not** in the repo and
must never be committed. `src/hackathon26/db.py` reads it automatically, so no manual copying is needed.

The local deployment uses a self-signed certificate, so clients must disable cert validation
(`nocertcheck` in GUI clients). That is fine for 127.0.0.1 only.

## 2. Python

```bash
uv sync
uv run python src/hackathon26/db.py     # -> Connected to Exasol 2026.2.0-nano.8 at 127.0.0.1:8563
```

`src/hackathon26/db.py` resolves settings from `.env` first (see `.env.example`), then falls back to the
local deployment files, so a fresh checkout works with no config.

## 3. Exasol MCP server (AI agents query the DB directly)

Enabled and registered for Claude Code at **project scope**, so it's shared via `.mcp.json`:

```bash
exasol mcp enable
claude mcp add --transport http --scope project exasol-personal http://127.0.0.1:4896/mcp
```

Status: `exasol mcp status` → serving at `http://127.0.0.1:4896/mcp`.

This matters for the demo: it lets an agent explore the schema and run SQL with the database enforcing
what it can see — a real part of our "evidence, not vibes" trust story.

## 4. Kiro CLI

```bash
curl -fsSL https://cli.kiro.dev/install | bash   # installs to ~/.local/bin/kiro-cli
kiro-cli login                                    # GitHub sign-in
```

Installed: v3.3.0, logged in. Model guidance is in [CLAUDE.md](CLAUDE.md).

## 5. AWS CLI

Installed: **2.40.2** (`brew install awscli`). Not yet configured — run `aws configure sso`
or `aws configure`. Needed for Bedrock if we call Claude from the app.

## Known gotchas

- **Disk space.** This machine runs tight. The Exasol starter kit (`exasol-labs/exasol-personal-local-starterkit`)
  refuses to install below 20 GB free. We don't need it — the launcher already provides the database and the
  MCP server; the kit only adds `exapump` and sample datasets. To reclaim space:
  `npm cache clean --force`, `uv cache clean`, `brew cleanup -s --prune=all`, and clear `~/Library/Caches/*.ShipIt`.
- **GitHub.** This machine has two accounts. The active one must be `Rakif215`:
  `gh auth switch --user Rakif215`. A push as `Rakif21` gets a 403.
- **8 GB RAM** is the documented minimum for Exasol Personal and the VM claims 4 GB. Expect the machine to be
  slow with the DB plus a browser plus an IDE. `exasol stop` when not using it.
