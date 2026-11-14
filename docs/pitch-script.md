# MedGuard: 3-minute pitch script

Demo file: `web/medguard-pitch.html` (12 steps, keys only). About 420 spoken words.
Text in [brackets] is for the team to fill in or check before the pitch.

| Time | Part | Screen |
|---|---|---|
| 0:00–0:35 | **1. The problem** (Challenge 1 + Challenge 3) | Demo, step 1 |
| 0:35–1:55 | **2. Our solution, live** (12 key presses) | Demo, steps 1–12 |
| 1:55–2:10 | **3. Why you can trust it** | Demo, last step (workflow on the right) |
| 2:10–2:45 | **4. Business** | 1–2 slides |
| 2:45–3:00 | **5. Closing** | Closing slide |

Tip: two people. One speaks, one presses the keys, so the speaker never looks down.

---

## 1. The problem · 0:00–0:35

> **Would you trust an AI with your health?** *(pause)* Not if it's just confident.
>
> Here is what a doctor deals with every day. Older heart patients take five to ten medicines, and they don't
> know the names. They say "*the red one… and the white one*". The pharmacy switches the maker and the pill
> looks different. A painkiller from another doctor never makes it onto the list, because "it's only for the pain".
>
> The information is all there: the prescription, the pharmacy, the blood tests, the official leaflets. It's
> just scattered. Healthcare doesn't lack data. **It lacks connected intelligence you can trust.**
>
> That's **MedGuard**: a second pair of ears in the consultation room. It connects the data, and when it isn't
> sure, it doesn't guess. **It asks.**

*(Step 1 is already on screen.)*

---

## 2. Our solution, live · 0:35–1:55

About 6–7 seconds per press. Say the line, then press.

| Key | Step | Say |
|---|---|---|
| (on screen) | 1 · start | "Frau Weber, 72, routine heart check-up. MedGuard listens. Only the doctor sees what it says." |
| → | 2 · dizzy | "She mentions dizziness. Two of her tablets lower blood pressure, so MedGuard **suggests** a quick check. It suggests; it doesn't decide." |
| → | 3 · "the white one" | "Now the hard part. *The white one* could be **two** of her medicines. MedGuard shows both, highlights the difference, and suggests **one** question: round or oval?" |
| → | 4 · "oval, with a line" | "91 percent. Still not certain, so it suggests one more question." |
| → | 5 · "with my coffee" | "Now everything matches, and **Dr. Vogel** marks it as metoprolol." |
| → | 6 · water tablet | "She admits she sometimes skips her water tablet…" |
| → | 7 · "twice a week" | "…and it goes into her record." |
| → | 8 · knee tablets | "Then, in passing: tablets for her knee. **Not on her prescription.** And they look just like her water tablet." |
| → | 9 · "Ibuprofen 400" | "The box is in her bag: ibuprofen." |
| → | 10 · the check | "MedGuard checks it against her medicines, the official leaflet and her blood results. Her kidney function is falling, and the leaflet warns about exactly this combination. It **suggests discussing it**, with the source quoted word for word." |
| → | 11 · decision | "Dr. Vogel talks to her. MedGuard offers the paperwork: pause the painkiller, order a kidney test." |
| → | 12 · final report | "Everything from the visit lands in one report. The doctor reviews it, unticks anything that shouldn't go in, and signs." *(Click **Sign report**.)* |

If you're running late, skip steps 6 and 7 with two quick presses and no talking.

---

## 3. Why you can trust it · 1:55–2:10

*(Point at the dark panel on the right.)*

> Three rules. **It shows its evidence:** every suggestion comes from her record, the pill database, her blood
> tests or the official leaflet. **It asks instead of deciding:** the doctor makes every call. And **the data
> stays put:** everything is joined in **Exasol** in one query. The AI only writes the wording.

---

## 4. Business · 2:10–2:45

*(Slide: who pays · why now · three steps.)*

> **Who pays:** GP practices and cardiology outpatient clinics, as a monthly subscription per doctor:
> [price, e.g. €X per doctor per month].
>
> **Why now:** Germany's electronic patient record and e-prescriptions are making medication data available
> to practices. [Check the current rollout status before the pitch.]
>
> **How we get there:**
> 1. **Pilot** with [2–3] heart-failure practices here in the Medical Valley region.
> 2. **Integrate** into the practice software doctors already use, so there's no extra screen.
> 3. **Expand** to pharmacies and health insurers, who carry the cost of hospital stays caused by medication errors.
>
> **Regulation:** decision-support software for a specific patient is likely a medical device under the EU MDR.
> We start with a supervised pilot and build the certification path from day one.

---

## 5. Closing · 2:45–3:00

> We're looking for **[pilot practices / clinical partners / help with regulation]**.
>
> So: would you trust an AI with your health? You can trust this one, because it shows its evidence, says when
> it isn't sure, and leaves the decision to your doctor.
>
> Thank you.

---

## Before the pitch

- **Rehearse with a timer, twice.** The demo part must fit in 80 seconds.
- **Open the demo full screen** and click it once, so the keys and the clicker respond. Press **R** to start
  from step 1.
- **Fill in every [bracket].** Don't present a number nobody has checked.
- **If the demo breaks:** say "let me show you the key moment", press → to step 3, and talk over the two
  candidates.

### Likely questions

- *"What if she can't describe the pill and doesn't have it with her?"* → MedGuard shows the photos so she can
  point, checks the pharmacy history, or saves it as "described, not verified" for follow-up. The safety check
  still runs, because it works on the ingredient, not the exact product.
- *"Same medicine from two different companies?"* → MedGuard knows every maker's version and how each one looks,
  and suggests the question that tells them apart.
- *"Isn't this a medical device?"* → Likely, yes. See the regulation line in the business part.
- *"Where does the data come from?"* → The patient record, lab results, a pill-appearance database and the
  official leaflets, all joined in Exasol.
