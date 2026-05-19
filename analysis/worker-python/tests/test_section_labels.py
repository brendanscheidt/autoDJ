from autodj_analysis import (
    PROJECT_SECTION_LABELS,
    SectionMappingEvidence,
    map_section_label,
    normalize_section_label,
)


def test_project_section_vocabulary_matches_dubstep_transition_policy() -> None:
    assert PROJECT_SECTION_LABELS == (
        "intro",
        "verse",
        "build",
        "drop",
        "break",
        "outro",
        "unknown",
    )


def test_direct_dj_labels_and_synonyms_map_without_extra_evidence() -> None:
    assert normalize_section_label("Break / Verse") == "break/verse"

    assert map_section_label("intro", confidence=0.99, provider_name="test").label == "intro"
    assert map_section_label("drop", confidence=0.99, provider_name="test").label == "drop"

    breakdown = map_section_label("breakdown", confidence=0.8, provider_name="test")
    assert breakdown.label == "break"
    assert breakdown.confidence == 0.8
    assert breakdown.notes == ("test label normalized",)

    break_verse = map_section_label("break/verse", confidence=0.75, provider_name="test")
    assert break_verse.label == "break"
    assert break_verse.notes == ("test label normalized",)


def test_pop_form_chorus_requires_drop_evidence_before_promotion() -> None:
    weak = map_section_label("chorus", confidence=0.92, provider_name="candidate")

    assert weak.label == "unknown"
    assert weak.confidence == 0.45
    assert "requires energy/bass/onset/phrase evidence" in weak.notes[0]

    strong = map_section_label(
        "chorus",
        confidence=0.92,
        evidence=SectionMappingEvidence(
            energy_mean=0.74,
            bass_energy_mean=0.68,
            onset_density_mean=0.53,
            phrase_boundary_confidence=0.81,
        ),
        provider_name="candidate",
    )

    assert strong.label == "drop"
    assert strong.confidence == 0.70
    assert "promoted to drop" in strong.notes[0]


def test_contextual_labels_require_evidence_for_build_or_break_promotion() -> None:
    pre_chorus = map_section_label(
        "pre-chorus",
        confidence=0.77,
        evidence=SectionMappingEvidence(energy_slope=0.18, onset_density_mean=0.42),
        provider_name="candidate",
    )
    assert pre_chorus.label == "build"
    assert pre_chorus.confidence == 0.68

    instrumental_break = map_section_label(
        "instrumental",
        confidence=0.76,
        evidence=SectionMappingEvidence(energy_mean=0.30, bass_energy_mean=0.24, energy_slope=-0.02),
        provider_name="candidate",
    )
    assert instrumental_break.label == "break"
    assert instrumental_break.confidence == 0.64

    unsupported_bridge = map_section_label("bridge", confidence=0.85, provider_name="candidate")
    assert unsupported_bridge.label == "unknown"
    assert unsupported_bridge.confidence == 0.45


def test_non_section_and_unknown_labels_stay_low_confidence_unknown() -> None:
    silence = map_section_label("silence", confidence=0.95, provider_name="candidate")
    assert silence.label == "unknown"
    assert silence.confidence == 0.30
    assert "not a usable DJ section" in silence.notes[0]

    unsupported = map_section_label("unsupported-label", confidence=0.95, provider_name="candidate")
    assert unsupported.label == "unknown"
    assert unsupported.confidence == 0.35
