"""Dubstep phrase-label experiment built from ML boundaries plus signal evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from importlib import metadata
import time
from typing import Any

from .. import __version__
from ..audio_io import DecodedAudio
from ..features import EnergyFeatures, compute_energy_features
from .all_in_one_backend import ALL_IN_ONE_UNLOCKED_BACKEND, AllInOneUnlockedBackend
from .base import (
    AnalysisContext,
    BackendExecutionError,
    BeatGridCandidateResult,
    CandidateProvenance,
    FeatureBundle,
    SectionCandidate,
    SectionCandidateResult,
)
from .registry import BackendRegistry
from .songformer_backend import SONGFORMER_BACKEND, SongFormerBackend


DUBSTEP_PHRASE_HYBRID_BACKEND = "dubstep-phrase-hybrid"
DUBSTEP_PHRASE_HYBRID_MODEL_NAME = "dubstep-phrase-hybrid"
DUBSTEP_PHRASE_HYBRID_MODEL_VERSION = "boundary-fusion-v1"

_DROP_SOURCE_LABELS = frozenset(("chorus", "drop", "hook", "inst", "instrumental", "solo"))
_DROP_EXIT_LABELS = frozenset(("break", "bridge", "intro", "outro", "silence", "solo", "verse"))
_BUILD_BARS = (4, 8, 16, 32)
_DROP_END_BARS = (16, 32, 48, 64)
_TURNAROUND_MAX_BARS = 8
_DROP_CLUSTER_MAX_SPAN_BARS = 32


@dataclass(frozen=True)
class _SourceSection:
    start_seconds: float
    end_seconds: float
    mapped_label: str
    source_label: str
    provider: str
    confidence: float


@dataclass(frozen=True)
class _Boundary:
    time_seconds: float
    snapped_seconds: float
    beat_index: int | None
    source_labels: tuple[str, ...]
    mapped_labels: tuple[str, ...]
    providers: tuple[str, ...]


@dataclass(frozen=True)
class _DropAnchor:
    time_seconds: float
    beat_index: int | None
    score: float
    boundary: _Boundary
    features: Mapping[str, float] = field(default_factory=dict)
    internal_anchors: tuple[_DropAnchor, ...] = ()


@dataclass(frozen=True)
class _PlannedSection:
    type: str
    start_seconds: float
    end_seconds: float
    confidence: float
    source_label: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class DubstepPhraseHybridBackend:
    """Infer DJ sections from structural boundaries, phrase lengths, and signal curves."""

    name = DUBSTEP_PHRASE_HYBRID_BACKEND

    def __init__(
        self,
        *,
        all_in_one_backend: Any | None = None,
        songformer_backend: Any | None = None,
        energy_extractor: Callable[..., EnergyFeatures] = compute_energy_features,
        backend_version: str = __version__,
    ) -> None:
        self._all_in_one_backend = all_in_one_backend
        self._songformer_backend = songformer_backend
        self._energy_extractor = energy_extractor
        self._backend_version = backend_version

    def analyze_sections(
        self,
        audio: DecodedAudio,
        features: FeatureBundle,
        beat_grid: BeatGridCandidateResult,
        context: AnalysisContext,
    ) -> SectionCandidateResult:
        start = time.perf_counter()
        warnings: list[str] = [
            "Experimental dubstep phrase inference; labels are for POC inspection, not final production confidence.",
        ]
        try:
            energy_features = (
                features.energy if isinstance(features.energy, EnergyFeatures) else self._energy_extractor(audio)
            )
            source_results = self._source_results(audio, energy_features, beat_grid, context)
            source_sections = _source_sections(source_results)
            boundaries = _fused_boundaries(source_sections, beat_grid)
            planned = _plan_sections(
                boundaries,
                source_sections,
                energy_features,
                beat_grid,
                duration_seconds=context.duration_seconds,
            )
            warnings.extend(_source_warnings(source_results))
            if not planned:
                warnings.append("Hybrid inference found no defensible drop anchors.")
            return SectionCandidateResult(
                status="ok",
                provenance=self._provenance(
                    parameters={
                        "sourceBackends": [ALL_IN_ONE_UNLOCKED_BACKEND, SONGFORMER_BACKEND],
                        "sourceSectionCount": len(source_sections),
                        "boundaryCount": len(boundaries),
                        "sectionCount": len(planned),
                        "dropAnchorCount": sum(section.type == "drop" for section in planned),
                        "buildBars": list(_BUILD_BARS),
                        "dropEndBars": list(_DROP_END_BARS),
                    },
                    processing_seconds=_elapsed(start),
                    warnings=tuple(warnings),
                ),
                sections=tuple(
                    _section_candidate(section, index=index, beat_grid=beat_grid)
                    for index, section in enumerate(planned)
                ),
                cue_points=tuple(_cue_point(section, index=index, beat_grid=beat_grid) for index, section in enumerate(planned) if section.type == "drop"),
            )
        except Exception as exc:
            return SectionCandidateResult(
                status="failed",
                provenance=self._provenance(processing_seconds=_elapsed(start), warnings=tuple(warnings)),
                error=BackendExecutionError(
                    code="dubstep_phrase_hybrid_failed",
                    message=str(exc),
                    backend_name=self.name,
                    details={"exceptionType": type(exc).__name__},
                ),
            )

    def _source_results(
        self,
        audio: DecodedAudio,
        energy_features: EnergyFeatures,
        beat_grid: BeatGridCandidateResult,
        context: AnalysisContext,
    ) -> tuple[SectionCandidateResult, ...]:
        all_in_one = self._all_in_one_backend or AllInOneUnlockedBackend()
        songformer = self._songformer_backend or SongFormerBackend()
        bundle = FeatureBundle(energy=energy_features)
        return (
            all_in_one.analyze_sections(audio, bundle, beat_grid, context),
            songformer.analyze_sections(audio, bundle, beat_grid, context),
        )

    def _provenance(
        self,
        *,
        parameters: Mapping[str, Any] | None = None,
        processing_seconds: float = 0.0,
        warnings: tuple[str, ...] = (),
    ) -> CandidateProvenance:
        return CandidateProvenance(
            backend_name=self.name,
            backend_version=self._backend_version,
            model_name=DUBSTEP_PHRASE_HYBRID_MODEL_NAME,
            model_version=DUBSTEP_PHRASE_HYBRID_MODEL_VERSION,
            dependency_versions=_dependency_versions(),
            parameters=parameters or {},
            processing_seconds=processing_seconds,
            warnings=warnings,
        )


def register_dubstep_phrase_hybrid_backends(registry: BackendRegistry) -> None:
    registry.register_section(DUBSTEP_PHRASE_HYBRID_BACKEND, DubstepPhraseHybridBackend)


def _source_results_ok(results: Sequence[SectionCandidateResult]) -> tuple[SectionCandidateResult, ...]:
    return tuple(result for result in results if result.status == "ok")


def _source_warnings(results: Sequence[SectionCandidateResult]) -> list[str]:
    warnings: list[str] = []
    for result in results:
        warnings.extend(result.provenance.warnings)
        if result.status != "ok" and result.error is not None:
            warnings.append(f"{result.provenance.backend_name}: {result.error.message}")
    return warnings


def _source_sections(results: Sequence[SectionCandidateResult]) -> tuple[_SourceSection, ...]:
    sections: list[_SourceSection] = []
    for result in _source_results_ok(results):
        provider = result.provenance.backend_name
        for section in result.sections:
            sections.append(
                _SourceSection(
                    start_seconds=section.start_seconds,
                    end_seconds=section.end_seconds,
                    mapped_label=section.type,
                    source_label=(section.source_label or section.type).strip().lower(),
                    provider=provider,
                    confidence=section.confidence,
                )
            )
    return tuple(sorted(sections, key=lambda section: (section.start_seconds, section.end_seconds)))


def _fused_boundaries(
    source_sections: Sequence[_SourceSection],
    beat_grid: BeatGridCandidateResult,
    *,
    tolerance_seconds: float = 0.35,
) -> tuple[_Boundary, ...]:
    raw: list[tuple[float, _SourceSection]] = []
    for section in source_sections:
        if section.start_seconds > 0.05:
            raw.append((section.start_seconds, section))
        raw.append((section.end_seconds, section))
    raw.sort(key=lambda item: item[0])

    groups: list[list[tuple[float, _SourceSection]]] = []
    for item in raw:
        if not groups or abs(item[0] - _mean(time for time, _section in groups[-1])) > tolerance_seconds:
            groups.append([item])
        else:
            groups[-1].append(item)

    boundaries = []
    for group in groups:
        time_seconds = _mean(time for time, _section in group)
        snapped_seconds, beat_index = _snap_to_beat(time_seconds, beat_grid)
        active = [
            section
            for section in source_sections
            if section.start_seconds <= time_seconds + 0.05 < section.end_seconds
        ]
        group_sections = [section for _time, section in group]
        labels = tuple(sorted({section.source_label for section in (*group_sections, *active) if section.source_label}))
        mapped = tuple(sorted({section.mapped_label for section in (*group_sections, *active) if section.mapped_label}))
        providers = tuple(sorted({section.provider for section in (*group_sections, *active) if section.provider}))
        boundaries.append(
            _Boundary(
                time_seconds=_round_float(time_seconds),
                snapped_seconds=_round_float(snapped_seconds),
                beat_index=beat_index,
                source_labels=labels,
                mapped_labels=mapped,
                providers=providers,
            )
        )
    return tuple(boundaries)


def _plan_sections(
    boundaries: Sequence[_Boundary],
    source_sections: Sequence[_SourceSection],
    energy_features: EnergyFeatures,
    beat_grid: BeatGridCandidateResult,
    *,
    duration_seconds: float,
) -> tuple[_PlannedSection, ...]:
    beat_seconds = _beat_seconds(beat_grid)
    bar_seconds = beat_seconds * 4.0
    drop_anchors = _drop_anchors(boundaries, energy_features, beat_grid, bar_seconds=bar_seconds)
    if not drop_anchors:
        return ()

    planned: list[_PlannedSection] = []
    cursor = 0.0
    previous_drop_end: float | None = None
    for drop_index, anchor in enumerate(drop_anchors):
        next_drop_start = drop_anchors[drop_index + 1].time_seconds if drop_index + 1 < len(drop_anchors) else duration_seconds
        build_start = _build_start(
            anchor.time_seconds,
            boundaries,
            energy_features,
            bar_seconds=bar_seconds,
            cursor=cursor,
        )
        drop_end = _drop_end(
            anchor.time_seconds,
            boundaries,
            energy_features,
            bar_seconds=bar_seconds,
            next_drop_start=next_drop_start,
            duration_seconds=duration_seconds,
        )
        if (
            previous_drop_end is not None
            and anchor.time_seconds <= previous_drop_end + _TURNAROUND_MAX_BARS * bar_seconds
        ):
            _extend_previous_drop_for_reentry(planned, anchor=anchor, drop_end=drop_end)
            cursor = max(cursor, drop_end)
            previous_drop_end = cursor
            continue
        if build_start > cursor + 0.25:
            planned.append(
                _PlannedSection(
                    type="break" if previous_drop_end is not None else ("intro" if cursor <= 0.05 else "verse"),
                    start_seconds=cursor,
                    end_seconds=build_start,
                    confidence=0.58,
                    source_label="phrase-context",
                    metadata={"reason": "pre-build region", "dropAnchorSeconds": anchor.time_seconds},
                )
            )
        if anchor.time_seconds > build_start + 0.25:
            planned.append(
                _PlannedSection(
                    type="build",
                    start_seconds=build_start,
                    end_seconds=anchor.time_seconds,
                    confidence=0.66,
                    source_label="phrase-backsolve",
                    metadata={"dropAnchorSeconds": anchor.time_seconds, "allowedBuildBars": list(_BUILD_BARS)},
                )
            )
        planned.append(
            _PlannedSection(
                type="drop",
                start_seconds=anchor.time_seconds,
                end_seconds=drop_end,
                confidence=_round_float(min(0.86, max(0.56, anchor.score))),
                source_label="drop-anchor",
                metadata={
                    "anchorScore": anchor.score,
                    "anchorFeatures": dict(anchor.features),
                    "sourceLabels": list(anchor.boundary.source_labels),
                    "sourceProviders": list(anchor.boundary.providers),
                    "beatIndex": anchor.beat_index,
                    "internalDropAnchors": _internal_anchor_metadata(anchor),
                },
            )
        )
        cursor = max(cursor, drop_end)
        previous_drop_end = drop_end

    if cursor < duration_seconds - 0.25:
        trailing_type = "outro" if _mean_curve(energy_features.curve, cursor, duration_seconds) < 0.32 else "break"
        planned.append(
            _PlannedSection(
                type=trailing_type,
                start_seconds=cursor,
                end_seconds=duration_seconds,
                confidence=0.54,
                source_label="trailing-context",
                metadata={"reason": "post-final-drop region"},
            )
        )
    return _merge_and_clip(planned, source_sections, duration_seconds=duration_seconds)


def _internal_anchor_metadata(anchor: _DropAnchor) -> list[dict[str, Any]]:
    return [
        {
            "timeSeconds": _round_float(internal.time_seconds),
            "beatIndex": internal.beat_index,
            "anchorScore": internal.score,
            "classification": "drop_part_or_turnaround",
            "anchorFeatures": dict(internal.features),
            "sourceLabels": list(internal.boundary.source_labels),
            "sourceProviders": list(internal.boundary.providers),
        }
        for internal in anchor.internal_anchors
    ]


def _extend_previous_drop_for_reentry(
    planned: list[_PlannedSection],
    *,
    anchor: _DropAnchor,
    drop_end: float,
) -> None:
    for index in range(len(planned) - 1, -1, -1):
        previous = planned[index]
        if previous.type != "drop":
            continue
        metadata = dict(previous.metadata)
        internal = list(metadata.get("internalDropAnchors", ()))
        internal.append(
            {
                "timeSeconds": _round_float(anchor.time_seconds),
                "beatIndex": anchor.beat_index,
                "anchorScore": anchor.score,
                "classification": "drop_reentry_or_turnaround",
            }
        )
        metadata["internalDropAnchors"] = internal
        planned[index] = replace(
            previous,
            end_seconds=max(previous.end_seconds, drop_end),
            confidence=_round_float(max(previous.confidence, min(0.86, anchor.score))),
            metadata=metadata,
        )
        return


def _drop_anchors(
    boundaries: Sequence[_Boundary],
    energy_features: EnergyFeatures,
    beat_grid: BeatGridCandidateResult,
    *,
    bar_seconds: float,
) -> tuple[_DropAnchor, ...]:
    scored: list[_DropAnchor] = []
    for boundary in boundaries:
        if boundary.snapped_seconds < max(2.0, 2.0 * bar_seconds):
            continue
        before_start = max(0.0, boundary.snapped_seconds - 4.0 * bar_seconds)
        after_end = boundary.snapped_seconds + 8.0 * bar_seconds
        before_energy = _mean_curve(energy_features.curve, before_start, boundary.snapped_seconds)
        after_energy = _mean_curve(energy_features.curve, boundary.snapped_seconds, after_end)
        after_bass = _mean_curve(energy_features.bass_energy_curve, boundary.snapped_seconds, after_end)
        onset_peak = _max_curve(energy_features.onset_density_curve, boundary.snapped_seconds - 0.20, boundary.snapped_seconds + 0.45)
        jump = after_energy - before_energy
        label_support = 1.0 if any(label in _DROP_SOURCE_LABELS for label in boundary.source_labels) else 0.0
        provider_support = min(1.0, len(boundary.providers) / 2.0)
        phrase_support = _phrase_support(boundary.beat_index)
        score = (
            0.22 * label_support
            + 0.16 * provider_support
            + 0.19 * after_energy
            + 0.17 * after_bass
            + 0.15 * max(0.0, jump)
            + 0.07 * onset_peak
            + 0.04 * phrase_support
        )
        features = {
            "beforeEnergy": _round_float(before_energy),
            "afterEnergy": _round_float(after_energy),
            "afterBassEnergy": _round_float(after_bass),
            "energyJump": _round_float(jump),
            "onsetPeak": _round_float(onset_peak),
            "labelSupport": _round_float(label_support),
            "providerSupport": _round_float(provider_support),
            "phraseSupport": _round_float(phrase_support),
        }
        has_drop_label = any(label in _DROP_SOURCE_LABELS for label in boundary.source_labels)
        has_intro_label = "intro" in boundary.source_labels
        has_exit_label = any(label in _DROP_EXIT_LABELS for label in boundary.source_labels)
        has_strong_energy_entry = after_energy >= 0.58 and after_bass >= 0.48 and jump >= 0.12
        has_signal_support = after_energy >= 0.45 or after_bass >= 0.32 or (jump >= 0.18 and onset_peak >= 0.55)
        has_provider_support = provider_support >= 1.0 or (jump >= 0.18 and after_bass >= 0.50)
        looks_like_early_intro = has_intro_label and after_energy < 0.55 and after_bass < 0.45
        looks_like_exit = has_exit_label and after_energy < 0.48 and after_bass < 0.42 and (
            jump < -0.06
            or (jump <= 0.0 and after_energy < 0.45)
            or (jump <= 0.0 and ("outro" in boundary.source_labels or "silence" in boundary.source_labels))
        )
        if (
            score >= 0.58
            and has_provider_support
            and (has_drop_label or has_strong_energy_entry)
            and has_signal_support
            and not looks_like_early_intro
            and not looks_like_exit
        ):
            scored.append(
                _DropAnchor(
                    time_seconds=boundary.snapped_seconds,
                    beat_index=boundary.beat_index,
                    score=_round_float(score),
                    boundary=boundary,
                    features=features,
                )
            )

    clusters: list[list[_DropAnchor]] = []
    min_gap = 26.0 * bar_seconds
    max_cluster_span = _DROP_CLUSTER_MAX_SPAN_BARS * bar_seconds
    for candidate in sorted(scored, key=lambda anchor: anchor.time_seconds):
        if not clusters:
            clusters.append([candidate])
            continue

        previous_time = clusters[-1][-1].time_seconds
        cluster_start_time = clusters[-1][0].time_seconds
        is_near_previous = candidate.time_seconds - previous_time < min_gap
        is_within_parent_span = candidate.time_seconds - cluster_start_time <= max_cluster_span
        if is_near_previous and is_within_parent_span:
            clusters[-1].append(candidate)
        else:
            clusters.append([candidate])
    return tuple(_best_anchor_cluster(cluster, bar_seconds=bar_seconds) for cluster in clusters)


def _best_anchor_cluster(cluster: Sequence[_DropAnchor], *, bar_seconds: float) -> _DropAnchor:
    best_anchor = max(cluster, key=lambda anchor: anchor.score)
    best_score = best_anchor.score
    entry_candidates = [
        anchor
        for anchor in cluster
        if anchor.score >= best_score - 0.08 and _looks_like_drop_entry(anchor)
    ]
    if entry_candidates:
        selected = min(entry_candidates, key=lambda anchor: anchor.time_seconds)
        internal_anchors = tuple(anchor for anchor in cluster if anchor is not selected)
        return replace(selected, internal_anchors=internal_anchors)

    nearby_early = [
        anchor
        for anchor in cluster
        if anchor.score >= best_score - 0.25
        and anchor.time_seconds <= best_anchor.time_seconds
        and best_anchor.time_seconds - anchor.time_seconds <= _TURNAROUND_MAX_BARS * bar_seconds
        and anchor.features.get("phraseSupport", 0.0) >= 0.75
        and (
            anchor.features.get("onsetPeak", 0.0) >= 0.55
            or anchor.features.get("afterEnergy", 0.0) >= 0.48
            or anchor.features.get("afterBassEnergy", 0.0) >= 0.50
        )
    ]
    selected = nearby_early[0] if nearby_early else best_anchor
    internal_anchors = tuple(anchor for anchor in cluster if anchor is not selected)
    return replace(selected, internal_anchors=internal_anchors)


def _looks_like_drop_entry(anchor: _DropAnchor) -> bool:
    """Favor true energy-entry boundaries over high sustained energy inside a drop."""

    energy_jump = float(anchor.features.get("energyJump", 0.0))
    after_energy = float(anchor.features.get("afterEnergy", 0.0))
    after_bass = float(anchor.features.get("afterBassEnergy", 0.0))
    phrase_support = float(anchor.features.get("phraseSupport", 0.0))
    if energy_jump >= 0.12 and after_bass >= 0.48:
        return True
    if phrase_support >= 0.75 and after_bass >= 0.55:
        return True
    if energy_jump >= 0.18 and after_energy >= 0.62 and after_bass >= 0.42:
        return True
    return False


def _build_start(
    drop_start: float,
    boundaries: Sequence[_Boundary],
    energy_features: EnergyFeatures,
    *,
    bar_seconds: float,
    cursor: float,
) -> float:
    candidates = [
        boundary
        for boundary in boundaries
        if cursor + 0.25 <= boundary.snapped_seconds < drop_start - 0.25
    ]
    scored: list[tuple[float, float]] = []
    for boundary in candidates:
        bars_before_drop = (drop_start - boundary.snapped_seconds) / bar_seconds
        phrase_score = _build_phrase_support(bars_before_drop)
        if phrase_score <= 0.0:
            continue
        before_energy = _mean_curve(
            energy_features.curve,
            max(cursor, boundary.snapped_seconds - 4.0 * bar_seconds),
            boundary.snapped_seconds,
        )
        after_energy = _mean_curve(
            energy_features.curve,
            boundary.snapped_seconds,
            min(drop_start, boundary.snapped_seconds + 4.0 * bar_seconds),
        )
        onset_peak = _max_curve(
            energy_features.onset_density_curve,
            boundary.snapped_seconds - 0.20,
            boundary.snapped_seconds + 0.45,
        )
        jump = max(0.0, after_energy - before_energy)
        length_bonus = 0.03 if bars_before_drop >= 15.0 else (0.015 if bars_before_drop >= 7.0 else 0.0)
        score = 0.48 * phrase_score + 0.50 * jump + 0.05 * onset_peak + length_bonus
        scored.append((score, boundary.snapped_seconds))
    if scored:
        return _round_float(max(scored, key=lambda item: item[0])[1])

    fallback = max(cursor, drop_start - 8.0 * bar_seconds)
    return _round_float(fallback)


def _drop_end(
    drop_start: float,
    boundaries: Sequence[_Boundary],
    energy_features: EnergyFeatures,
    *,
    bar_seconds: float,
    next_drop_start: float,
    duration_seconds: float,
) -> float:
    min_end = drop_start + 8.0 * bar_seconds
    max_end = min(next_drop_start - 2.0 * bar_seconds, duration_seconds)
    if max_end <= min_end:
        return _round_float(max(min_end, drop_start))
    candidates = [
        boundary
        for boundary in boundaries
        if min_end <= boundary.snapped_seconds <= max_end
    ]
    for boundary in candidates:
        if _looks_like_turnaround(boundary, candidates, energy_features, bar_seconds=bar_seconds):
            continue
        if _is_drop_exit_boundary(boundary, drop_start, energy_features, bar_seconds=bar_seconds):
            return _round_float(boundary.snapped_seconds)

    targets = [drop_start + bars * bar_seconds for bars in _DROP_END_BARS]
    best = _nearest([boundary.snapped_seconds for boundary in candidates], targets, tolerance=max(1.5, 1.5 * bar_seconds))
    if best is not None:
        return _round_float(best)
    return _round_float(min(max_end, drop_start + 16.0 * bar_seconds))


def _looks_like_turnaround(
    boundary: _Boundary,
    candidates: Sequence[_Boundary],
    energy_features: EnergyFeatures,
    *,
    bar_seconds: float,
) -> bool:
    window_end = boundary.snapped_seconds + _TURNAROUND_MAX_BARS * bar_seconds
    boundary_after_energy = _mean_curve(
        energy_features.curve,
        boundary.snapped_seconds,
        boundary.snapped_seconds + 4.0 * bar_seconds,
    )
    boundary_after_bass = _mean_curve(
        energy_features.bass_energy_curve,
        boundary.snapped_seconds,
        boundary.snapped_seconds + 4.0 * bar_seconds,
    )
    for later in candidates:
        if later.snapped_seconds <= boundary.snapped_seconds + 0.25 or later.snapped_seconds > window_end:
            continue
        later_after_energy = _mean_curve(
            energy_features.curve,
            later.snapped_seconds,
            later.snapped_seconds + 4.0 * bar_seconds,
        )
        later_after_bass = _mean_curve(
            energy_features.bass_energy_curve,
            later.snapped_seconds,
            later.snapped_seconds + 4.0 * bar_seconds,
        )
        has_drop_label = any(label in _DROP_SOURCE_LABELS for label in later.source_labels)
        has_reentry_energy = later_after_energy >= 0.50 or later_after_bass >= 0.42
        has_clear_lift = (
            later_after_energy >= boundary_after_energy + 0.05
            or later_after_bass >= boundary_after_bass + 0.05
        )
        if has_drop_label and (has_reentry_energy or has_clear_lift):
            return True
    return False


def _is_drop_exit_boundary(
    boundary: _Boundary,
    drop_start: float,
    energy_features: EnergyFeatures,
    *,
    bar_seconds: float,
) -> bool:
    drop_elapsed_bars = (boundary.snapped_seconds - drop_start) / bar_seconds
    if drop_elapsed_bars < 8.0:
        return False

    before_energy = _mean_curve(energy_features.curve, drop_start, boundary.snapped_seconds)
    after_energy = _mean_curve(
        energy_features.curve,
        boundary.snapped_seconds,
        boundary.snapped_seconds + 4.0 * bar_seconds,
    )
    after_bass = _mean_curve(
        energy_features.bass_energy_curve,
        boundary.snapped_seconds,
        boundary.snapped_seconds + 4.0 * bar_seconds,
    )
    energy_drop = before_energy - after_energy
    has_exit_label = any(label in _DROP_EXIT_LABELS for label in boundary.source_labels)
    has_terminal_label = "outro" in boundary.source_labels or "silence" in boundary.source_labels
    strong_sustained_drop = energy_drop >= 0.18 and after_energy < 0.50
    clear_low_exit = energy_drop >= 0.10 and (after_energy < 0.46 or after_bass < 0.30)
    phrase_exit = _drop_end_phrase_support(drop_elapsed_bars) >= 0.75 and energy_drop >= 0.08 and after_energy < 0.48

    if has_terminal_label and (clear_low_exit or after_energy < 0.42):
        return True
    if drop_elapsed_bars >= 8.0 and has_exit_label and clear_low_exit:
        return True
    if drop_elapsed_bars >= 12.0 and has_exit_label and phrase_exit:
        return True
    return drop_elapsed_bars >= 16.0 and strong_sustained_drop


def _drop_end_phrase_support(drop_elapsed_bars: float) -> float:
    nearest = min(_DROP_END_BARS, key=lambda bars: abs(drop_elapsed_bars - bars))
    distance = abs(drop_elapsed_bars - nearest)
    if distance <= 0.75:
        return 1.0
    if distance <= 1.5:
        return 0.75
    return 0.0


def _build_phrase_support(bars_before_drop: float) -> float:
    nearest = min(_BUILD_BARS, key=lambda bars: abs(bars_before_drop - bars))
    distance = abs(bars_before_drop - nearest)
    if distance <= 0.75:
        return 1.0
    if distance <= 1.5:
        return 0.65
    return 0.0


def _merge_and_clip(
    sections: Sequence[_PlannedSection],
    source_sections: Sequence[_SourceSection],
    *,
    duration_seconds: float,
) -> tuple[_PlannedSection, ...]:
    del source_sections
    clipped: list[_PlannedSection] = []
    last_end = 0.0
    for section in sorted(sections, key=lambda item: (item.start_seconds, item.end_seconds)):
        start = max(last_end, max(0.0, section.start_seconds))
        end = min(duration_seconds, section.end_seconds)
        if end <= start + 0.05:
            continue
        if clipped and clipped[-1].type == section.type and section.type in {"intro", "break", "outro", "verse"}:
            previous = clipped.pop()
            clipped.append(
                _PlannedSection(
                    type=previous.type,
                    start_seconds=previous.start_seconds,
                    end_seconds=end,
                    confidence=max(previous.confidence, section.confidence),
                    source_label=previous.source_label,
                    metadata=dict(previous.metadata),
                )
            )
        else:
            clipped.append(
                _PlannedSection(
                    type=section.type,
                    start_seconds=_round_float(start),
                    end_seconds=_round_float(end),
                    confidence=section.confidence,
                    source_label=section.source_label,
                    metadata=dict(section.metadata),
                )
            )
        last_end = end
    return tuple(clipped)


def _section_candidate(section: _PlannedSection, *, index: int, beat_grid: BeatGridCandidateResult) -> SectionCandidate:
    start_seconds, start_index = _snap_to_beat(section.start_seconds, beat_grid)
    end_seconds, end_index = _snap_to_beat(section.end_seconds, beat_grid)
    return SectionCandidate(
        id=f"section-{section.type}-{index + 1:03d}",
        type=section.type,  # type: ignore[arg-type]
        start_seconds=_round_float(start_seconds),
        end_seconds=_round_float(max(start_seconds, end_seconds)),
        confidence=section.confidence,
        source_label=section.source_label,
        start_beat_index=start_index,
        end_beat_index=end_index,
        mapping_notes=("dubstep phrase heuristic inferred label from ML boundaries and signal evidence",),
        provider_metadata={
            "sourceBackend": DUBSTEP_PHRASE_HYBRID_BACKEND,
            **dict(section.metadata),
        },
    )


def _cue_point(section: _PlannedSection, *, index: int, beat_grid: BeatGridCandidateResult) -> dict[str, Any]:
    time_seconds, beat_index = _snap_to_beat(section.start_seconds, beat_grid)
    return {
        "id": f"cue-drop-{index + 1:03d}",
        "type": "drop",
        "timeSeconds": _round_float(time_seconds),
        "sectionId": f"section-drop-{index + 1:03d}",
        "confidence": section.confidence,
        "tags": ["experimental", "dubstep_phrase_hybrid", "beat_snapped"],
        "beatIndex": beat_index,
    }


def _snap_to_beat(time_seconds: float, beat_grid: BeatGridCandidateResult) -> tuple[float, int | None]:
    if not beat_grid.beats:
        return (time_seconds, None)
    nearest = min(beat_grid.beats, key=lambda beat: abs(beat.time_seconds - time_seconds))
    return (nearest.time_seconds, nearest.index)


def _beat_seconds(beat_grid: BeatGridCandidateResult) -> float:
    diffs = [
        later.time_seconds - earlier.time_seconds
        for earlier, later in zip(beat_grid.beats, beat_grid.beats[1:])
        if later.time_seconds > earlier.time_seconds
    ]
    return _median(diffs) if diffs else 60.0 / 140.0


def _phrase_support(beat_index: int | None) -> float:
    if beat_index is None:
        return 0.0
    if beat_index % 64 == 0:
        return 1.0
    if beat_index % 32 == 0:
        return 0.9
    if beat_index % 16 == 0:
        return 0.75
    remainder = beat_index % 16
    return 0.25 if remainder in {1, 15} else 0.0


def _mean_curve(curve: Sequence[Mapping[str, float]], start: float, end: float) -> float:
    values = [float(point["value"]) for point in curve if start <= float(point["timeSeconds"]) <= end]
    return _mean(values) if values else 0.0


def _max_curve(curve: Sequence[Mapping[str, float]], start: float, end: float) -> float:
    values = [float(point["value"]) for point in curve if start <= float(point["timeSeconds"]) <= end]
    return max(values) if values else 0.0


def _nearest(values: Sequence[float], targets: Sequence[float], *, tolerance: float) -> float | None:
    best_value = None
    best_distance = float("inf")
    for value in values:
        for target in targets:
            distance = abs(value - target)
            if distance < best_distance:
                best_value = value
                best_distance = distance
    return best_value if best_value is not None and best_distance <= tolerance else None


def _mean(values: Any) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded


def _elapsed(start: float) -> float:
    return round(max(0.0, time.perf_counter() - start), 6)


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in ("numpy", "scipy", "librosa", "allin1", "transformers", "torch"):
        try:
            versions[package_name] = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            continue
    return versions
