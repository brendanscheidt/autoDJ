"""Shared semantic cue-provider helpers for AutoDJ section labels."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .section_labels import SectionLabel, map_section_label


SEMANTIC_CUE_BOUNDARIES = frozenset({"start", "end"})


@dataclass(frozen=True)
class ParsedSemanticCueLabel:
    section_type: SectionLabel
    boundary: str
    ordinal: int | None
    source_label: str


@dataclass(frozen=True)
class SemanticCueBoundary:
    time_seconds: float
    name: str
    section_type: SectionLabel
    boundary: str
    ordinal: int | None = None
    cue_num: int | None = None
    color: dict[str, int] | None = None


def parse_semantic_cue_label(name: str, *, provider_name: str = "manual") -> ParsedSemanticCueLabel | None:
    """Parse labels like ``drop_1_start``, ``build_2_end``, or ``build_2``.

    Rekordbox exposes hot cue names as free text. AutoDJ treats names that end
    in ``_start`` or ``_end`` as semantic section boundaries. Labels shaped
    like ``section_ordinal`` are treated as start boundaries so Rekordbox hot
    cues can stay concise.
    """

    parts = [part for part in name.strip().lower().split("_") if part]
    if len(parts) < 2:
        return None
    boundary = parts[-1]
    if boundary in SEMANTIC_CUE_BOUNDARIES:
        label_parts = parts[:-1]
    elif boundary.isdigit():
        boundary = "start"
        label_parts = parts
    else:
        return None
    ordinal = None
    if label_parts and label_parts[-1].isdigit():
        ordinal = int(label_parts[-1])
        label_parts = label_parts[:-1]
    if not label_parts:
        return None
    source_label = "_".join(label_parts)
    mapping = map_section_label(source_label, provider_name=provider_name)
    if mapping.label == "unknown":
        return None
    return ParsedSemanticCueLabel(
        section_type=mapping.label,
        boundary=boundary,
        ordinal=ordinal,
        source_label=source_label,
    )


def boundaries_from_named_cues(
    cues: Sequence[Any],
    *,
    provider_name: str = "manual",
) -> tuple[SemanticCueBoundary, ...]:
    """Extract semantic boundaries from cue-like objects with name/time fields."""

    boundaries: list[SemanticCueBoundary] = []
    for cue in cues:
        name = str(getattr(cue, "name", "") or "")
        parsed = parse_semantic_cue_label(name, provider_name=provider_name)
        if parsed is None:
            continue
        boundaries.append(
            SemanticCueBoundary(
                time_seconds=float(getattr(cue, "start_seconds")),
                name=name,
                section_type=parsed.section_type,
                boundary=parsed.boundary,
                ordinal=parsed.ordinal,
                cue_num=getattr(cue, "num", None),
                color=dict(getattr(cue, "color", {}) or {}),
            )
        )
    return tuple(sorted(boundaries, key=lambda boundary: boundary.time_seconds))


def sections_and_cue_points_from_boundaries(
    boundaries: Sequence[SemanticCueBoundary],
    *,
    duration_seconds: float,
    provider_name: str,
    beat_index_for_time: Callable[[float], int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build analyzed-track sections/cues from semantic boundaries."""

    ordered = sorted(boundaries, key=lambda boundary: boundary.time_seconds)
    starts = [boundary for boundary in ordered if boundary.boundary == "start"]
    ends: dict[tuple[SectionLabel, int | None], SemanticCueBoundary] = {}
    for boundary in ordered:
        if boundary.boundary == "end":
            ends[(boundary.section_type, boundary.ordinal)] = boundary

    sections: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for index, start in enumerate(starts):
        explicit_end = ends.get((start.section_type, start.ordinal))
        next_start = starts[index + 1] if index + 1 < len(starts) else None
        if explicit_end is not None and explicit_end.time_seconds > start.time_seconds:
            end_seconds = explicit_end.time_seconds
        elif next_start is not None and next_start.time_seconds > start.time_seconds:
            end_seconds = next_start.time_seconds
        else:
            end_seconds = duration_seconds
        if end_seconds <= start.time_seconds:
            continue
        counts[start.section_type] += 1
        ordinal = start.ordinal or counts[start.section_type]
        section_id = f"section-{provider_name}-{start.section_type}-{ordinal:03d}"
        sections.append(
            {
                "id": section_id,
                "type": start.section_type,
                "startSeconds": _round_float(start.time_seconds),
                "endSeconds": _round_float(end_seconds),
                "confidence": 1.0,
                "startBeatIndex": beat_index_for_time(start.time_seconds),
                "endBeatIndex": beat_index_for_time(end_seconds),
                "source": provider_name,
                "sourceCueName": start.name,
            }
        )

    cue_points: list[dict[str, Any]] = []
    section_by_key = {
        (section["type"], int(section["id"].rsplit("-", 1)[-1])): str(section["id"])
        for section in sections
    }
    counts.clear()
    for boundary in ordered:
        counts[boundary.section_type] += 1
        ordinal = boundary.ordinal or counts[boundary.section_type]
        section_id = section_by_key.get((boundary.section_type, ordinal), "")
        cue_type = boundary.section_type if boundary.boundary == "start" else "mix_out"
        cue_points.append(
            {
                "id": f"cue-{provider_name}-{_safe_id(boundary.name)}",
                "type": cue_type,
                "timeSeconds": _round_float(boundary.time_seconds),
                "sectionId": section_id,
                "confidence": 1.0,
                "tags": [provider_name, "semantic_boundary", boundary.boundary],
                "beatIndex": beat_index_for_time(boundary.time_seconds),
                "sourceCueName": boundary.name,
                "rekordboxNum": boundary.cue_num,
                "color": dict(boundary.color or {}),
            }
        )
    cue_points.sort(key=lambda cue: float(cue["timeSeconds"]))
    return sections, cue_points


def _safe_id(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "cue"


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded
