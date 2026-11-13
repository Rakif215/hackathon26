from datetime import date

from hackathon26.listener.models import TranscriptSegment
from hackathon26.resolution.models import RecordedMedication, ResolveRequest
from hackathon26.resolution.resolve import resolve_segment


def request(text, **updates):
    return ResolveRequest(segment=TranscriptSegment.model_validate({
        "schema_version": "1", "event_id": "e1", "consultation_id": "c1", "segment_id": "s1",
        "revision": 1, "sequence": 1, "speaker": "PATIENT", "text": text,
        "is_final": True, "source": "script", "occurred_at": "2026-11-13T10:00:00Z",
    } | updates), as_of=date(2026, 11, 13))


def medicines():
    return [
        RecordedMedication(patient_med_id=11, drug_id=1, generic_name="Ramipril",
                           strength="5 mg", color="white", shape="round", appearance_strength="5 mg",
                           manufacturer="Synthetic A", appearance_source="invented demo appearance"),
        RecordedMedication(patient_med_id=12, drug_id=2, generic_name="Metoprolol succinate",
                           strength="25 mg", color="white", shape="oval", appearance_strength="25 mg",
                           manufacturer="Synthetic B", appearance_source="invented demo appearance"),
    ]


def resolve(text, meds=None, **updates):
    return resolve_segment(1, request(text, **updates), medicines() if meds is None else meds)


def test_white_one_preserves_rival_candidates_and_provenance():
    result = resolve("I take the white one.")
    mention = result.resolutions[0]
    assert mention.status == "CANDIDATES"
    assert [c.drug_id for c in mention.candidates] == [1, 2]
    assert {c.match_level for c in mention.candidates} == {"COLOUR_MATCH"}
    assert mention.candidates[0].patient_med_id == 11
    assert mention.candidates[0].appearance_source == "invented demo appearance"
    assert mention.needs_review is True
    assert result.persisted is False


def test_shape_narrows_candidates_without_confirmation():
    result = resolve("I take the white oval one.").resolutions[0]
    assert [c.drug_id for c in result.candidates] == [2]
    assert result.candidates[0].match_level == "COLOUR_SHAPE_MATCH"
    assert result.status == "CANDIDATES"


def test_conflicting_shape_does_not_fall_back_to_color():
    assert resolve("I take the blue oval one.").resolutions[0].candidates == []


def test_small_size_is_not_silently_verified():
    result = resolve("I take the little white one.").resolutions[0]
    assert any("size" in note.lower() for note in result.limitations)


def test_named_match_handles_salt_suffix_and_is_not_confirmed():
    result = resolve("I take metoprolol.").resolutions[0]
    assert [c.drug_id for c in result.candidates] == [2]
    assert result.candidates[0].match_level == "NAME_MATCH"
    assert result.needs_review is True


def test_unnamed_knee_medicine_does_not_infer_a_drug_or_class():
    result = resolve("I take something for my knee.").resolutions[0]
    assert result.status == "UNRESOLVED"
    assert result.candidates == []


def test_other_person_negated_historical_and_uncertain_contexts_are_not_resolved():
    for text in ["My husband takes ramipril.", "I don't take ramipril.",
                 "I used to take ramipril.", "Maybe I take ramipril.", "Ramipril."]:
        result = resolve(text).resolutions[0]
        assert result.status == "CONTEXT_REVIEW"
        assert result.candidates == []


def test_missing_or_wrong_strength_appearance_is_not_matched():
    wrong = medicines()[0].model_copy(update={"appearance_strength": "10 mg"})
    assert resolve("I take the white one.", [wrong]).resolutions[0].candidates == []
    missing = medicines()[0].model_copy(update={"appearance_source": None})
    assert resolve("I take the white one.", [missing]).resolutions[0].candidates == []


def test_partial_segment_does_not_generate_candidates():
    result = resolve("I take ramipril", is_final=False)
    assert result.status == "PROVISIONAL"
    assert result.resolutions == []


def test_named_drug_outside_list_is_not_claimed_absent_from_all_records():
    result = resolve("I take ibuprofen.").resolutions[0]
    assert result.status == "UNRESOLVED"
    assert "recorded list" in " ".join(result.limitations).lower()


def test_linked_name_and_conflicting_appearance_require_review():
    result = resolve("I take ramipril, the blue oval one.")
    assert all(r.status == "CONTEXT_REVIEW" for r in result.resolutions)
    assert all(not r.candidates for r in result.resolutions)
    assert any("conflict" in note.lower() for note in result.resolutions[0].limitations)


def test_appearance_alternatives_preserve_imprint_provenance():
    first = medicines()[0].model_copy(update={"imprint": "DEMO A"})
    second = medicines()[0].model_copy(update={"imprint": "DEMO B"})
    result = resolve("I take the white one.", [first, second]).resolutions[0]
    assert [c.imprint for c in result.candidates] == ["DEMO A", "DEMO B"]


def test_long_white_one_matches_canonical_oblong_furosemide():
    furosemide = RecordedMedication(patient_med_id=13, drug_id=3, generic_name="Furosemide",
                                   strength="40 mg", color="white", shape="oblong",
                                   appearance_strength="40 mg", appearance_source="synthetic fixture")
    result = resolve("I take the long white one.", [medicines()[0], furosemide]).resolutions[0]
    assert result.mention.raw_text == "the long white one"
    assert [candidate.drug_id for candidate in result.candidates] == [3]
    assert result.candidates[0].match_level == "COLOUR_SHAPE_MATCH"


def test_oblong_word_after_color_is_also_resolved():
    furosemide = medicines()[0].model_copy(update={"drug_id": 3, "shape": "oblong"})
    assert resolve("I take the white oblong one.", [furosemide]).resolutions[0].candidates[0].drug_id == 3
