# Handoff: where things stand (13 Nov 2026, evening)

Read this first, then CLAUDE.md, PROJECT.md and docs/pitch-script.md.

## The demo (what we present)

- **`web/medguard-pitch.html`**: the current pitch demo as ONE standalone file (plain HTML + JS, pill photos embedded).
  Open it in any browser. It is a fixed 1600×900 stage scaled to the window: no scrolling, keys only.
  - → / Space / clicker: next · ← back · R start over · 1 / 2 pick the doctor's choice.
  - 12 steps. Three columns: conversation + MedGuard suggestion card (left), prescription + today's actions /
    final report + patient history (middle), animated "behind the scenes" Exasol workflow (right).
  - Verified in headless Chrome at 1600×900: every step fits, including the final report and "More questions".
- The same design also lives on the Claude design canvas (artboard `Pitch.dc.html`,
  https://claude.ai/artifact/UbgdQQ2p3iohAh51133CWn). A 22-step backup is the artboard `Pitch22.dc.html`
  and the git tag `pitch-22-steps`.
- Source for the standalone file is the canvas version's logic, ported to vanilla JS. If you edit the story,
  edit `web/medguard-pitch.html` directly (the `LIST` array holds every step).

## Agreed rules for the demo (the user's decisions)

- MedGuard **suggests and asks; it never gives verdicts**. Every suggestion offers the doctor a choice
  (button 1 / 2). Every question the doctor chooses to ask is asked and answered on screen before moving on;
  if the doctor skips, the follow-up step is skipped too (`onlyIf`).
- Keep the design **simple and minimal**. Avoid heavy context and lots of colour. Make small changes, one at a time.
- Core moment for the mentor's question: "the white one" could be two medicines → shown side by side with the
  differences highlighted → one suggested question → the doctor confirms.

## Pitch

- `docs/pitch-script.md`: 3-minute script. Opens and closes on Challenge 3's question
  ("Would you trust an AI with your health?"). Brackets [like this] still need real values from the team
  (price, pilot count, the ask, ePA status).

## Not done yet

- Business / go-to-market slides (1–2 slides: pilot → integrate → expand).
- Nothing is wired to the real Exasol database or Bedrock yet. The demo is scripted. The schema is in
  `sql/01_schema.sql`, the helpers in `src/hackathon26/db.py` and `src/hackathon26/bedrock.py` work.

## Environment

See SETUP.md. AWS credentials expire every few hours: copy them from the Workshop Studio dashboard and run
`./scripts/aws_creds.sh`. Bedrock cap: under 1 request/second.
