# PROJECT.md — MedGuard

> Healthcare Hackathon Bayern · Erlangen · 12–14 Nov 2026
> **Primary track:** Challenge 3 — Exasol "Build healthcare AI you can trust"
> **Also targets:** Challenge 1 — BioMedical Design (the medication-communication need)

## One-liner

**A second pair of ears in the consultation room.** MedGuard follows the conversation between doctor and
patient, resolves the medications the patient can only describe ("the small yellow one", "something for my
knee"), checks them against what they already take *and against their own lab results*, and shows the doctor
the evidence — with the uncertainty left visible and the decision left to them.

## Why listening, and not a form

**Over-the-counter drugs.** Patients do not think ibuprofen is "medication". It is not on the med list, not in
the record, and nobody volunteers it. But it surfaces in conversation — *"my knee's been hurting, I've been
taking something for it."* A med-list tool can never catch that. A listening tool catches exactly that.

The same is true of the Challenge 1 need: vague pill descriptions only exist **in speech**. Both challenges
converge on one insight — *the information that matters is spoken, not recorded.*

## The demo (scripted, 90 seconds)

A heart-failure follow-up. Patient (72F) is on ramipril, metoprolol and furosemide.

1. She refers to "the white one" and "the small yellow one". MedGuard resolves both **against her own med
   list** using colour and shape, and shows its confidence.
2. She mentions, in passing, that her GP gave her *"something for my knee"*. MedGuard infers the drug class
   (NSAID) rather than a specific product, and says so.
3. It catches the **"triple whammy"**: NSAID + ACE inhibitor + loop diuretic, a documented acute kidney injury
   risk — quoting the package insert verbatim.
4. It pulls her **actual labs** from Exasol: eGFR falling (62 → 48), potassium 5.1. This is what makes the
   warning about *her*, not about drugs in general.
5. The doctor sees the risk, the evidence, the confidence, **and what the system could not verify**. They
   accept or override. It is logged.

The conversation is a **pre-loaded script replayed in the UI** — no live microphone. It demos identically
every time and spends no build time on speech recognition, which is not what is being judged.

## Architecture

```
scripted transcript (timestamped utterances)
        │
  [1] mention detection ......... local, no LLM per utterance (respects 1 req/s Bedrock cap)
        │
  [2] resolution ................ EXASOL: appearance + patient's own med list → candidates + confidence
        │
  [3] interaction check ......... EXASOL: candidate × current drugs → FDA label sections → verbatim quote
        │
  [4] patient context ........... EXASOL: recent labs + trend
        │
  [5] synthesis ................. Claude on Bedrock (Guardrails on), batched at conversation pauses
        │
  [6] clinician panel ........... risk · evidence · confidence · what it could NOT verify
        │
  [7] accept / override ......... audit log in Exasol
```

### Why retrieval lives in Exasol, not a Bedrock Knowledge Base

Both could store the FDA label text — but putting it in a Bedrock KB would demote Exasol to a bucket for
patient rows. Joining drug knowledge against patient medications and lab results **in one query** is exactly
the "connected intelligence" Exasol's brief asks for, and it is the thing we can defend on stage. It is also
faster to build: no vector store to provision or index.

Bedrock is used for what only it can do: Claude for extraction and synthesis, and **Guardrails** to block
dosing advice, diagnosis and PII leakage — a concrete, demonstrable trust artifact.

## How it maps to the Exasol judging lens

| Exasol build step | Our answer |
|---|---|
| **Pick** one user + one pain | The doctor in a HF follow-up. Pain: deciding with incomplete information, in minutes |
| **Connect** representative data | Synthetic patients, medications and **labs**, joined against public FDA/RxNorm drug knowledge, all in Exasol |
| **Build** one useful workflow | Follow a consultation → surface medication risks with evidence |
| **Prove** evidence + uncertainty | Verbatim insert quotes with section and document id; confidence by match basis (name > class > enzyme); ambiguous mentions show their rival candidates; an explicit "could not verify" note |
| **Show** human oversight | Nothing is auto-applied. Every finding ends in an accept/override, recorded in `CLINICIAN_REVIEW` and `AUDIT_LOG` |

## Trust rules (non-negotiable)

- **Never say "safe".** Absence of a documented interaction is reported as *"no documented interaction found"*,
  never as safety. No hit is the most common result and the most dangerous to misread.
- **Every claim is quoted.** A finding without a verbatim insert quote is a bug. The loader verifies the quote
  against the stored section text instead of trusting the model.
- **Show the alternatives.** When a mention is ambiguous, the rival candidates are shown, not hidden.
- **Name the blind spots.** Each finding carries what the system could *not* check.
- **No dosing, no diagnosis, no prescribing.** Enforced in prompt and in Bedrock Guardrails.

## MVP scope (must demo)

1. Transcript replay with live mention detection.
2. Vague-description resolution against the patient's own med list, with confidence and rival candidates.
3. Interaction check with verbatim FDA evidence and a severity signal.
4. Lab-aware risk context (the eGFR / potassium join).
5. Clinician panel with accept/override, written to the audit log.

## Stretch

- Duplicate active ingredient across two products (e.g. paracetamol twice).
- Cumulative effects across 3+ drugs (several potassium-raising drugs).
- German / English toggle.
- Speech recognition confidence shown on drug names (ASR mishears drug names badly — showing that is a
  trust feature, not a weakness).

## Out of scope

Real patient data, diagnosis, dosing advice, prescribing, live audio capture.

## Known limits (say these out loud in the pitch)

- **No hit does not mean safe.** Package inserts do not list every interaction.
- **US data.** openFDA labels and RxNorm are US; German SmPC text differs.
- **Pill appearance is unreliable in general** — generic substitution changes it. We only match within *one
  patient's own* med list, which is both more tractable and more accurate than a global pill database.
- In the EU, software giving patient-specific advice like this is usually a **medical device (MDR)**. This is
  a prototype on synthetic data.

## Status

- [x] Exasol schema (`sql/01_schema.sql`) — 16 tables, applied
- [ ] Seed data: synthetic patient, medications, labs
- [ ] FDA label ingestion (openFDA) for the demo drug set
- [ ] Mention detection + resolution
- [ ] Interaction + lab rules engine
- [ ] Bedrock synthesis + Guardrails
- [ ] Clinician UI

See [docs/product-idea.md](docs/product-idea.md) for the interaction-check design this builds on,
and [SETUP.md](SETUP.md) for the environment.
