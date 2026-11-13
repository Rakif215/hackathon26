# CONTEXT.md — Background for humans and AI agents

Raw context from the hackathon briefs. Read this before making product decisions.
For *what we're building*, see [PROJECT.md](PROJECT.md).

## Event

- Healthcare Hackathon Bayern, Erlangen, **12–14 November 2026** (Medical Valley EMN, Siemens Healthineers).
- Three days, so a believable prototype matters more than polish.

## Challenge 3: Exasol, "Would you trust an AI with your health?" (PRIMARY)

Exasol pitches itself as "the sovereign agentic database".

- **Problem:** healthcare doesn't lack data, it lacks *connected intelligence*. Patient history, lab results,
  hospital systems and clinical research are all separate. "Information everywhere. The full picture nowhere."
- **Trust test:** *Confident AI* says "Everything looks normal." (no sources, caveats or context).
  *Trustworthy AI* says "Here is the evidence. One result is missing. Please review with a clinician."
  That means **evidence shown, uncertainty flagged, human review.**
- **Mission:** Choose a meaningful healthcare problem, build an app people want, and explain why its insights
  deserve trust. "Your problem. Your user. Your models. One rule: Earn Trust."
- **Starting points (no fixed track):** help a patient (navigate a confusing care journey), help a hospital
  (spot operational bottlenecks), help a researcher (find patterns in clinical data).
- **Toolkit:** healthcare data (synthetic or authorized), then **Exasol Personal** (explore, combine, analyze),
  then your AI app (any model, agent or interface).
- **Build steps:** Pick (one user + one pain), Connect (representative data), Build (one useful workflow),
  Prove (evidence + uncertainty), Show (human oversight).
- "A believable prototype beats a perfect slide deck."

## Challenge 1: BioMedical Design (BMD), need-driven innovation (SECONDARY)

Speaker: Lars Svane (BMD, Denmark). The Biodesign method is need first, then ideas, then concept, then business.

- Need statement template: **"A way to [address the problem] for [population] in order to [outcome]."**
- Invention ≠ innovation. Diverge and then converge on needs before ideas.
- **Example need from the deck (the one we use):**
  > A method to bridge the information gap between healthcare professionals and heart-failure patients
  > regarding medications, aiming to increase self-sufficiency measured by a reduction in healthcare contacts.
- Observations behind it:
  - HF patients have comorbidities and take many prescribed and OTC drugs, several times a day, on different
    schedules and with extra instructions.
  - Phone consultations work well, but patients don't know drug names, and generics come under other brands.
  - There is no common, reliable source of a drug's **physical characteristics** (colour, shape) for HCPs.
  - Example dialogues: "three white tablets, 1 blue, 2 yellow"; "new prescription for the yellow pills";
    at the pharmacy, "same active ingredient, but it does look different… I'm confused!"
- Mentors: Koray Karakaya, Ph.D. (health innovation, start-ups, funding) and Kristian B. Laursen, M.D.
  (clinical, MedTech start-ups).

## Infrastructure we have

- **AWS account**: Bedrock (Claude models), S3, Lambda, etc.
- **Kiro credits (~1000)**: Kiro IDE + `kiro-cli`. Use for bulk coding to save Claude tokens (see CLAUDE.md).
- **Exasol Personal**: the database the challenge expects us to use.

## Constraints

- **Synthetic data only.** No real patient data anywhere in the repo.
- Not a medical device. The app must never give dosing or diagnostic advice and always defers to a clinician.
