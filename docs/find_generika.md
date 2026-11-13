## 1. The Commercial Standard: "Aut-idem" Group ID

To reliably show doctors all possible generic alternatives a patient might have received, we need the **Aut-idem Group ID** (Substitution Group ID). This is a proprietary foreign key provided by commercial German drug databases (like ABDATA or MMI).

It clusters all PZN (National Drug Code) variants that are 100% identical and legally substitutable based on:

1. **Active Ingredient** (e.g., Ramipril)
2. **Strength / Dosage** (e.g., 5 mg)
3. **Dosage Form** (e.g., Tablet / Film-coated tablet)

**The Application Flow:**

* **Input:** The system receives a specific PZN (e.g., from scanning a medication plan).
* **Lookup:** The backend queries the database: *"Which Aut-idem Group ID does this PZN belong to?"* (e.g., `Group 4711`).
* **Expansion:** The backend fetches all other PZNs linked to `Group 4711`.
* **Result:** The UI displays the "generic fan" – all physically different tablets the patient could potentially be taking.

---

## 2. The Zero-Cost Workaround (For Prototypes / MVPs)

Commercial database licenses are expensive. For an early MVP, we can build our own **Composite Grouping Key** using free, open data from the BfArM (Federal Institute for Drugs and Medical Devices).

Instead of a pre-calculated group ID, we concatenate three data points to create a custom matching string:
`[ATC-Code] + [Strength] + [Dosage Form]`

**Example for Ramipril 5mg:**

* **ATC-Code:** `C09AA05`
* **Strength:** `5mg`
* **Form:** `TAB`
* **Our Custom Key:** `C09AA05_5MG_TAB`

**How to use it:**
We run a script over the free BfArM dataset to generate this custom key for every medication. When the app scans a medication, it calculates the composite key and runs a simple SQL `WHERE custom_key = 'C09AA05_5MG_TAB'` to fetch all equivalent generics to display in the UI.