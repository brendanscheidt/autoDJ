"""Project section-label policy shared by semantic section candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SectionLabel = Literal["intro", "verse", "build", "drop", "break", "outro", "unknown"]

PROJECT_SECTION_LABELS: tuple[SectionLabel, ...] = (
    "intro",
    "verse",
    "build",
    "drop",
    "break",
    "outro",
    "unknown",
)

DIRECT_SECTION_LABELS: dict[str, SectionLabel] = {
    "break": "break",
    "break-verse": "break",
    "break/verse": "break",
    "breakdown": "break",
    "buildup": "build",
    "build-up": "build",
    "build": "build",
    "drop": "drop",
    "intro": "intro",
    "outro": "outro",
    "verse": "verse",
}

POP_DROP_LABELS = frozenset(("chorus", "hook", "refrain"))
CONTEXTUAL_BUILD_LABELS = frozenset(("pre-chorus", "prechorus", "pre-drop", "predrop"))
CONTEXTUAL_BUILD_OR_BREAK_LABELS = frozenset(("bridge", "inst", "instrumental", "solo"))
NON_SECTION_LABELS = frozenset(("end", "silence", "start"))


@dataclass(frozen=True)
class SectionMappingEvidence:
    """Optional evidence used before promoting pop-form labels into DJ labels."""

    energy_mean: float | None = None
    energy_peak: float | None = None
    bass_energy_mean: float | None = None
    onset_density_mean: float | None = None
    energy_slope: float | None = None
    phrase_boundary_confidence: float | None = None
    follows_build: bool | None = None


@dataclass(frozen=True)
class SectionLabelMapping:
    """Result of mapping a provider label to the AutoDJ section vocabulary."""

    label: SectionLabel
    confidence: float
    notes: tuple[str, ...]


def normalize_section_label(label: str) -> str:
    """Normalize provider labels while preserving slash semantics."""

    return " ".join(label.strip().lower().replace("_", "-").split()).replace(" / ", "/")


def map_section_label(
    label: str,
    *,
    confidence: float | None = None,
    evidence: SectionMappingEvidence | None = None,
    provider_name: str = "section-candidate",
) -> SectionLabelMapping:
    """Map provider labels into the conservative AutoDJ DJ-section vocabulary."""

    normalized = normalize_section_label(label)
    base_confidence = _clamp(confidence if confidence is not None else 0.60)
    evidence = evidence or SectionMappingEvidence()

    if normalized in DIRECT_SECTION_LABELS:
        mapped = DIRECT_SECTION_LABELS[normalized]
        note = f"{provider_name} label mapped directly" if mapped == normalized else f"{provider_name} label normalized"
        return SectionLabelMapping(mapped, _round_float(min(base_confidence, 0.82)), (note,))

    if normalized in POP_DROP_LABELS:
        if _has_drop_evidence(evidence):
            return SectionLabelMapping(
                "drop",
                _round_float(min(base_confidence, 0.70)),
                (f"{provider_name} pop-form label promoted to drop with energy/bass/onset/phrase evidence",),
            )
        return SectionLabelMapping(
            "unknown",
            _round_float(min(base_confidence, 0.45)),
            (f"{provider_name} pop-form label requires energy/bass/onset/phrase evidence before drop promotion",),
        )

    if normalized in CONTEXTUAL_BUILD_LABELS:
        if _has_build_evidence(evidence):
            return SectionLabelMapping(
                "build",
                _round_float(min(base_confidence, 0.68)),
                (f"{provider_name} contextual label promoted to build with rising-energy evidence",),
            )
        return SectionLabelMapping(
            "unknown",
            _round_float(min(base_confidence, 0.45)),
            (f"{provider_name} contextual label requires rising-energy evidence before build promotion",),
        )

    if normalized in CONTEXTUAL_BUILD_OR_BREAK_LABELS:
        if _has_build_evidence(evidence):
            return SectionLabelMapping(
                "build",
                _round_float(min(base_confidence, 0.64)),
                (f"{provider_name} contextual label promoted to build with rising-energy evidence",),
            )
        if _has_break_evidence(evidence):
            return SectionLabelMapping(
                "break",
                _round_float(min(base_confidence, 0.64)),
                (f"{provider_name} contextual label promoted to break with low-energy evidence",),
            )
        return SectionLabelMapping(
            "unknown",
            _round_float(min(base_confidence, 0.45)),
            (f"{provider_name} contextual label requires energy-slope evidence before build/break promotion",),
        )

    if normalized in NON_SECTION_LABELS:
        return SectionLabelMapping(
            "unknown",
            _round_float(min(base_confidence, 0.30)),
            (f"{provider_name} label is not a usable DJ section",),
        )

    return SectionLabelMapping(
        "unknown",
        _round_float(min(base_confidence, 0.35)),
        (f"{provider_name} emitted an unsupported label",),
    )


def _has_drop_evidence(evidence: SectionMappingEvidence) -> bool:
    return (
        _at_least(evidence.energy_mean, 0.62)
        and _at_least(evidence.bass_energy_mean, 0.50)
        and _at_least(evidence.onset_density_mean, 0.40)
        and (_at_least(evidence.phrase_boundary_confidence, 0.45) or evidence.follows_build is True)
    ) or (
        _at_least(evidence.energy_peak, 0.78)
        and _at_least(evidence.bass_energy_mean, 0.58)
        and evidence.follows_build is True
    )


def _has_build_evidence(evidence: SectionMappingEvidence) -> bool:
    return _at_least(evidence.energy_slope, 0.10) and (
        _at_least(evidence.onset_density_mean, 0.30) or _at_least(evidence.phrase_boundary_confidence, 0.45)
    )


def _has_break_evidence(evidence: SectionMappingEvidence) -> bool:
    return (
        _at_most(evidence.energy_mean, 0.45)
        and _at_most(evidence.bass_energy_mean, 0.45)
        and (evidence.energy_slope is None or evidence.energy_slope <= 0.04)
    )


def _at_least(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _at_most(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded
