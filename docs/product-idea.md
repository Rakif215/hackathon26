# Product idea: "Can I add this drug?" interaction check

> Status: **draft, to be confirmed by the team.** This shifts the focus away from pill identification
> (see [PROJECT.md](../PROJECT.md)) and onto drug compatibility only. If the team agrees, update PROJECT.md.

## One-liner

An assistant that answers **"The patient already takes drugs B, C and D. Can drug A be added?"** by checking the
official package inserts. Every answer shows the exact quote it is based on, how certain it is, and hands the
final decision to a clinician.

## The problem

- Heart-failure patients often take 5 to 10 drugs. Every new drug (a new prescription, an over-the-counter
  painkiller, an antibiotic) can interact with the ones they already take.
- The information exists, but it is spread over long package inserts. One insert often names a drug *class*
  ("ACE inhibitors", "strong CYP3A4 inhibitors") rather than the drug itself, so a simple name search misses it.
- The free US interaction service (NLM RxNav interaction API) was shut down in January 2024. Complete,
  structured interaction databases are commercial.
- A "confident AI" that says "these are fine together" is dangerous. A missing warning does not mean a
  combination is safe.

## Who it is for

**Primary user (assumption, to be confirmed):** a heart-failure nurse or pharmacist on a phone follow-up. The
patient asks "My GP gave me X. Is that OK with my other tablets?" The nurse needs a fast, sourced answer to
discuss with the responsible physician.

## How it works

The app checks the new drug A against each current drug, one pair at a time (A + B, A + C, A + D).

| Step | What happens | Data source |
|---|---|---|
| 1. Identify the drugs | Drug name → unique ID (RxCUI) and drug class, e.g. ramipril → "ACE inhibitor" | RxNorm / RxClass API (US National Library of Medicine) |
| 2. Read the package inserts | Fetch the official insert of A and of B. Search the *boxed warning*, *contraindications*, *warnings* and *drug interactions* sections for the other drug's name and classes | openFDA Drug Label API (US FDA) |
| 3. Check enzyme groups | If an insert warns about a group ("strong CYP3A4 inhibitors"), check whether the other drug belongs to it | FDA Table of Substrates, Inhibitors and Inducers |
| 4. Show the result | Traffic light, exact quote, source, confidence. A clinician confirms | Our app (Exasol + AI) |

All data sources are free and public. An LLM (Claude on Amazon Bedrock) can read the relevant section and
summarise the risk, but it must return a verbatim quote that the app checks against the source text.

### Traffic light (our app's rule, not an official scale)

| Colour | Meaning | Rule |
|---|---|---|
| Red | "The insert says do not combine" | Hit in the boxed warning or the contraindications section |
| Amber | "The insert describes an interaction or monitoring" | Hit in the warnings or drug interactions section |
| Grey | "No documented interaction found" | No hit. Never shown as "safe" |

## Example

Patient takes ramipril, metoprolol and furosemide. The doctor wants to add spironolactone.

| Pair | Result | Evidence |
|---|---|---|
| spironolactone + ramipril | **Amber** | Ramipril insert: *"Potassium-sparing diuretics (spironolactone, …) … can increase the risk of hyperkalemia."* The spironolactone insert says the same about ACE inhibitors. |
| spironolactone + metoprolol | Grey | No mention in either insert. |
| spironolactone + furosemide | Grey | No mention in either insert. |

These results come from real openFDA queries run on 13 Nov 2026.

## Why people can trust it (Exasol "Earn Trust" lens)

| Exasol step | Our answer |
|---|---|
| **Pick** one user + one pain | HF nurse on the phone: "Can the patient take this new drug with the others?" |
| **Connect** representative data | Synthetic patient medication lists plus public FDA and NLM drug data, stored and joined in **Exasol Personal** |
| **Build** one useful workflow | Enter the medication list and the new drug → one result per pair |
| **Prove** evidence + uncertainty | Every result shows the verbatim quote, the insert and section it comes from, and whether the match was by name (higher confidence) or by class/enzyme (lower confidence) |
| **Show** human oversight | Red, amber and low-confidence results go to a clinician review queue. The app never says "safe" and never gives dosing advice. Every check is logged |

## MVP scope (must demo)

1. Enter a synthetic patient's medication list and a candidate drug.
2. Steps 1–4 for every pair, with traffic light, quote and source.
3. Trust panel on every result: source, confidence, "please confirm with your clinician or pharmacist".
4. Clinician view with a review queue for red, amber and uncertain results.

## Stretch

- Same active ingredient taken twice (e.g. paracetamol in two products).
- Effects that add up across 3+ drugs (e.g. several drugs that raise potassium).
- German / English toggle.

## Out of scope

Real patient data, diagnosis, dosing advice, prescribing. The app supports a decision, it does not make it.

## Known limits

- **No hit does not mean safe.** Package inserts don't list every interaction.
- **US data only.** German products and the EU product information (SmPC) can differ.
- Inserts for the same generic drug vary by manufacturer. We use the newest one or check several.
- The class synonym list needs manual curation (inserts say "potassium-sparing diuretics", RxClass says
  "Aldosterone Antagonist").
- In the EU, software that gives this kind of advice for a specific patient is usually a medical device (MDR).
  For the hackathon this is a prototype on synthetic data only.

## Open questions for the team

- Is the primary user the nurse/pharmacist, or the patient directly?
- Do we keep pill identification at all, or drop it completely?
- Which 10–15 heart-failure drugs do we use for the demo data set?
