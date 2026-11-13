# PROJECT.md — What we're building

> Healthcare Hackathon Bayern · Erlangen · 12–14 Nov 2026 (Siemens Healthineers / Medical Valley EMN)
> **Primary track:** Challenge 3 — Exasol "Build healthcare AI you can trust"
> **Secondary:** Challenge 1 — BioMedical Design (BMD) need-driven innovation (borrow its validated need)

Status: **working concept, to be confirmed by the team.** Edit freely.

## One-liner (draft)

A trustworthy AI assistant that gives heart-failure / polypharmacy patients and their clinicians a
**shared, visual language for medications**, built on Exasol and showing the evidence behind every answer,
the uncertainty in it, and the point where a human clinician takes over.

## Need statement (BMD format)

> A way to **bridge the information gap about medications** for **chronic heart-failure patients on many drugs
> and the HCPs who phone them** in order to **reduce avoidable healthcare contacts and medication errors.**

Why this need: BMD's Challenge 1 deck validated it with real dialogues. Patients say "three white tablets and a
yellow one". Nurses can't see what a drug looks like. Generic substitution changes how a pill looks and
confuses patients.

## How it maps to the Exasol judging lens

| Exasol build step | Our answer |
|---|---|
| **Pick** one user + one pain | HF nurse on a phone follow-up and the patient on the other end. Pain: "which pill is that?" |
| **Connect** representative data | Synthetic patients, prescriptions and dispensing history plus a drug catalogue (name, active ingredient, strength, imprint, colour, shape, manufacturer) in **Exasol Personal** |
| **Build** one useful workflow | Patient describes a pill ("small yellow round, for the heart"). App matches it against *their* med list, shows pictures and explains it in plain language |
| **Prove** evidence + uncertainty | Every answer cites its source rows. Confidence score. Flags ambiguity (two yellow pills!), missing data and recent generic switches |
| **Show** human oversight | Low-confidence or risky matches go to clinician review. Nothing is changed without a human confirming. Audit log |

## MVP scope (must demo)

1. Patient medication list view, visual-first (colour, shape, imprint, what it's for, when to take it).
2. "Describe your pill" → ranked matches with evidence and a confidence score.
3. Generic-switch alert: "Your Metoprolol looks different this month. Same active ingredient."
4. Clinician view: same list, the patient's own words, and a review queue for uncertain matches.
5. Trust panel on every AI answer: sources, uncertainty, and "please confirm with your clinician".

## Stretch

- Photo of a pill → vision model → candidate match (always shown with uncertainty).
- Voice / phone-call transcript mode for the nurse.
- Interaction and duplicate-ingredient warnings (with sources).
- German / English toggle.

## Out of scope

Real patient data, diagnosis, dosing advice, prescribing.

## Pitch checklist (demo day)

- [ ] Real need, with the BMD dialogue as the opening story
- [ ] Live demo of one workflow end to end
- [ ] Show the "confident AI vs trustworthy AI" contrast on our own app
- [ ] Explain data flow and why Exasol (sovereign, in-database analytics)
- [ ] Human-in-the-loop moment shown explicitly
