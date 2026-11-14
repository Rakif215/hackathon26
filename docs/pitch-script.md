# MedGuard: 3-minute pitch script

Deck: `MedGuard_slides.html` (7 slides). The demo is the link on slide 5. Simple words, short sentences, and pauses
where marked. About 400 spoken words in all.

| Time | Slide | Part |
|---|---|---|
| 0:00–0:08 | 1 · Title | Who we are |
| 0:08–0:30 | 2 · The chatbot | The question |
| 0:30–0:55 | 3 · The problem | Why doctors need help |
| 0:55–1:15 | 4 · Our answer | What MedGuard does |
| 1:15–2:35 | 5 · Live demo | The demo, 12 key presses |
| 2:35–2:52 | 6 · What's next | Pilot, and our ask |
| 2:52–3:00 | 7 · Thank you | Closing line |

---

## Slide 1 · Title (0:00–0:08)

> Hi, we're Team MedGuard: Michael, Moeez and Rakif. We took on Challenge 3: healthcare AI you can trust.

## Slide 2 · The chatbot (0:08–0:30)

> Imagine your doctor types your symptoms into a chatbot. Swollen ankles, short of breath, kidneys getting worse.
> And it answers: *"Too much knitting. Have a cup of tea."*
> One hundred percent sure. No sources. No questions.
>
> *(pause)* Would your doctor trust that with your health?
>
> *(pause)* Not if it's just confident.

## Slide 3 · The problem (0:30–0:55)

> And doctors do need help. They have only a few minutes per patient, and so much to check:
> the patient's whole history, whether her pills match the prescription, and what she means when she says
> *"the red one"* and *"the white one"*.
>
> Older patients often take many medicines and don't know their names. That's where things get missed.

## Slide 4 · Our answer (0:55–1:15)

> So we built MedGuard: a second pair of ears in the consultation room.
> It listens. It checks everything against her data in **Exasol**: her record, blood tests, pill photos and the
> official leaflets. It suggests, and it shows the evidence. And the doctor always decides.
>
> Let me show you.

*(Switch to the demo tab.)*

## Slide 5 · Live demo (1:15–2:35)

*(The demo is on step 1. One person speaks, one presses →. The audience can read the conversation, so don't read it out.)*

| # | Key | Say |
|---|---|---|
| 1 | (on screen) | "Meet Frau Weber, 72, at her heart check-up. On the left, the conversation. On the right, what MedGuard does in the background. Only the doctor sees this." |
| 2 | → | "She feels dizzy. MedGuard checks her medicines and spots two that can cause it. It doesn't diagnose. It suggests a quick check." |
| 3 | → | "Now the tricky one: *the white one*. That could be two different pills. Instead of guessing, MedGuard suggests one simple question." *(point at the two pill photos)* |
| 4 | → | "She answers. MedGuard is more sure, but not sure enough. So it asks again." |
| 5 | → | "Now it all fits. The doctor confirms with one click." |
| 6 | → | "Her water tablet: she sometimes skips it…" |
| 7 | → | *(press without talking)* |
| 8 | → | "Then, almost by accident: pills for her knee. **Not on her list**, and they look exactly like her water tablet." |
| 9 | → | "The box says ibuprofen." |
| 10 | → | "This is the moment." *(pause)* "**Exasol** connects the dots: her kidney results are getting worse, and the official leaflet warns about exactly this mix. MedGuard shows the proof, word for word." *(point at the quote)* |
| 11 | → | "The doctor talks to her and decides. MedGuard just does the paperwork." |
| 12 | → | "One report: every source, every decision. The doctor checks it and signs." *(click **Sign report**)* "That's AI you can trust." |

*(Switch back to the slides.)* Don't click the suggestion buttons during the demo; pressing → counts each one as accepted.
If it runs long, skip steps 6–7 with two quick presses. If the demo breaks, open it again, press **R**, then → twice to step 3,
and talk over the two pill photos.

## Slide 6 · What's next (2:35–2:52)

> What's next? We start small: a supervised pilot with practices here in the Medical Valley.
> Then we build MedGuard into the software doctors already use. Then pharmacies and insurers.
> We're looking for pilot practices and clinical partners.
>
> So: would you trust an AI with your health? *(point at the line)* You can trust this one.

## Slide 7 · Thank you (2:52–3:00)

> Because it shows its evidence, says when it isn't sure, and leaves the decision to the doctor.
> Thank you.

---

## Before the pitch

- **Rehearse twice with a timer.** The demo has to fit in 80 seconds.
- **Open both tabs:** the slides in full screen (press **F**), and the demo already on step 1 (press **R**). Click once on each so the keys work.
- **Decide who says what.** For example: one person does slides 1–4, the second runs the demo keys, the third does slides 6–7.
- **No prices** in the pitch yet.

## Likely questions

- *"Is this live?"* → "It's a scripted walkthrough of how MedGuard works. The database and the AI connection are built; wiring them into this screen is next."
- *"What if she doesn't have the pill with her?"* → MedGuard shows photos so she can point, checks the pharmacy history, or saves it as "described, not verified" for later. The safety check still works, because it checks the ingredient.
- *"Same medicine from two companies?"* → MedGuard knows how each maker's version looks, and suggests the question that tells them apart.
- *"Isn't this a medical device?"* → Probably, under the EU MDR. That's why we start with a supervised pilot and plan certification from day one.
- *"Where does the data come from?"* → Her record, lab results, a pill-photo database and the official leaflets, all joined in Exasol. In the demo, the patient is invented.
