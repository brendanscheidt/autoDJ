"""Benchmark ranked drop anchors against Rekordbox drop-start cues."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import platform
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlparse

from ..cache import SCHEMA_VERSION, write_json_atomic
from ..drop_anchor_ranker import DropAnchorRankerOptions, rank_drop_anchors
from ..rekordbox_xml import RekordboxCue, RekordboxTrack, RekordboxXmlError, load_rekordbox_tracks
from ..semantic_cues import parse_semantic_cue_label


DROP_ANCHOR_BENCHMARK_REPORT_TYPE = "drop-anchor-ranker-benchmark"
DEFAULT_DROP_ANCHOR_TOP_K = 3
DEFAULT_DROP_ANCHOR_MATCH_TOLERANCE_SECONDS = 0.20


class DropAnchorBenchmarkError(ValueError):
    """Expected drop-anchor benchmark failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class DropStartReference:
    id: str
    time_seconds: float
    cue_name: str
    ordinal: int | None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "timeSeconds": _round_float(self.time_seconds),
            "cueName": self.cue_name,
        }
        if self.ordinal is not None:
            payload["ordinal"] = self.ordinal
        return payload


def run_drop_anchor_benchmark(
    rekordbox_xml_path: str | Path,
    analysis_root: str | Path,
    output_root: str | Path,
    *,
    top_k: int = DEFAULT_DROP_ANCHOR_TOP_K,
    match_tolerance_seconds: float = DEFAULT_DROP_ANCHOR_MATCH_TOLERANCE_SECONDS,
    ranker_options: DropAnchorRankerOptions | None = None,
) -> dict[str, Any]:
    """Rank drop anchors for analyzed tracks and compare to Rekordbox drop cues."""

    if top_k <= 0:
        raise DropAnchorBenchmarkError("invalid_top_k", "top_k must be greater than zero")
    if match_tolerance_seconds <= 0:
        raise DropAnchorBenchmarkError("invalid_match_tolerance", "match_tolerance_seconds must be greater than zero")

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        tracks = load_rekordbox_tracks(rekordbox_xml_path)
    except RekordboxXmlError as exc:
        raise DropAnchorBenchmarkError(exc.code, exc.message) from exc

    analyzed_index = _analyzed_artifact_index(Path(analysis_root))
    cases = []
    for track in tracks:
        match_key = _track_match_key(track)
        artifact_path = analyzed_index.get(match_key)
        if artifact_path is None:
            cases.append(_missing_case(track, match_key))
            continue
        cases.append(
            _run_case(
                track,
                artifact_path,
                output_root,
                top_k=top_k,
                match_tolerance_seconds=match_tolerance_seconds,
                ranker_options=ranker_options,
            )
        )

    summary = {
        "schemaVersion": SCHEMA_VERSION,
        "reportType": DROP_ANCHOR_BENCHMARK_REPORT_TYPE,
        "createdAtUtc": _utc_now_iso(),
        "rekordboxXmlPath": str(rekordbox_xml_path),
        "analysisRoot": str(analysis_root),
        "outputRoot": str(output_root),
        "parameters": {
            "topK": top_k,
            "matchToleranceSeconds": match_tolerance_seconds,
            "ranker": (ranker_options or DropAnchorRankerOptions()).__dict__,
        },
        "cases": cases,
        "summary": _summary(cases, top_k=top_k),
    }
    write_json_atomic(output_root / "drop-anchor-benchmark-summary.json", summary)
    return summary


def _run_case(
    track: RekordboxTrack,
    artifact_path: Path,
    output_root: Path,
    *,
    top_k: int,
    match_tolerance_seconds: float,
    ranker_options: DropAnchorRankerOptions | None,
) -> dict[str, Any]:
    artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    case_dir = output_root / _safe_path_name(artifact.get("trackId") or Path(artifact_path).parent.name)
    case_dir.mkdir(parents=True, exist_ok=True)
    ranking = rank_drop_anchors(artifact, options=ranker_options)
    ranking_path = write_json_atomic(case_dir / "drop-anchor-ranking.json", ranking)
    references = _drop_start_references(track)
    matches = [
        _reference_match(reference, ranking["candidates"], top_k=top_k, tolerance_seconds=match_tolerance_seconds)
        for reference in references
    ]
    nearest_beat_matches = [
        _nearest_beat_upper_bound_match(reference, artifact, tolerance_seconds=match_tolerance_seconds)
        for reference in references
    ]
    return {
        "trackName": track.name,
        "trackId": str(artifact.get("trackId") or ""),
        "analyzedTrackPath": str(artifact_path),
        "rankingPath": str(ranking_path),
        "referenceDropStarts": [reference.to_dict() for reference in references],
        "topCandidates": ranking["candidates"][:top_k],
        "matches": matches,
        "nearestBeatUpperBoundMatches": nearest_beat_matches,
        "metrics": {
            "referenceDropCount": len(references),
            "top1HitCount": sum(1 for match in matches if match["matchedWithinTop1"]),
            f"top{top_k}HitCount": sum(1 for match in matches if match["matchedWithinTopK"]),
            "missingWithinTopKCount": sum(1 for match in matches if not match["matchedWithinTopK"]),
            "nearestBeatUpperBoundHitCount": sum(
                1 for match in nearest_beat_matches if match["matchedWithinTolerance"]
            ),
            "nearestBeatUpperBoundMissCount": sum(
                1 for match in nearest_beat_matches if not match["matchedWithinTolerance"]
            ),
            "medianBestErrorMilliseconds": _round_optional(
                _median([abs(float(match["bestErrorMilliseconds"])) for match in matches if match["bestErrorMilliseconds"] is not None])
            ),
        },
    }


def _reference_match(
    reference: DropStartReference,
    candidates: Sequence[dict[str, Any]],
    *,
    top_k: int,
    tolerance_seconds: float,
) -> dict[str, Any]:
    best = None
    best_error = None
    for candidate in candidates:
        error = float(candidate["timeSeconds"]) - reference.time_seconds
        if best is None or abs(error) < abs(float(best_error)):
            best = candidate
            best_error = error
    matched_top_k = False
    matched_candidate = None
    for candidate in candidates[:top_k]:
        error = float(candidate["timeSeconds"]) - reference.time_seconds
        if abs(error) <= tolerance_seconds:
            matched_top_k = True
            matched_candidate = candidate
            break
    matched_top_1 = False
    if candidates:
        top_candidate = candidates[0]
        matched_top_1 = abs(float(top_candidate["timeSeconds"]) - reference.time_seconds) <= tolerance_seconds
    return {
        "reference": reference.to_dict(),
        "matchedWithinTop1": matched_top_1,
        "matchedWithinTopK": matched_top_k,
        "matchedCandidate": matched_candidate,
        "bestRank": int(best["rank"]) if best is not None else None,
        "bestCandidateTimeSeconds": _round_float(float(best["timeSeconds"])) if best is not None else None,
        "bestErrorMilliseconds": _round_float(float(best_error) * 1000.0) if best_error is not None else None,
    }


def _nearest_beat_upper_bound_match(
    reference: DropStartReference,
    artifact: dict[str, Any],
    *,
    tolerance_seconds: float,
) -> dict[str, Any]:
    beats = _beat_grid_entries(artifact)
    if not beats:
        return {
            "reference": reference.to_dict(),
            "matchedWithinTolerance": False,
            "nearestBeatIndex": None,
            "nearestBeatTimeSeconds": None,
            "nearestBeatErrorMilliseconds": None,
        }
    nearest_index, nearest_time = min(beats, key=lambda beat: abs(beat[1] - reference.time_seconds))
    error_seconds = nearest_time - reference.time_seconds
    return {
        "reference": reference.to_dict(),
        "matchedWithinTolerance": abs(error_seconds) <= tolerance_seconds,
        "nearestBeatIndex": nearest_index,
        "nearestBeatTimeSeconds": _round_float(nearest_time),
        "nearestBeatErrorMilliseconds": _round_float(error_seconds * 1000.0),
    }


def _missing_case(track: RekordboxTrack, match_key: str) -> dict[str, Any]:
    return {
        "trackName": track.name,
        "trackId": "",
        "analyzedTrackPath": None,
        "rankingPath": None,
        "referenceDropStarts": [reference.to_dict() for reference in _drop_start_references(track)],
        "topCandidates": [],
        "matches": [],
        "metrics": {
            "referenceDropCount": 0,
            "top1HitCount": 0,
            "top3HitCount": 0,
            "missingWithinTopKCount": 0,
            "nearestBeatUpperBoundHitCount": 0,
            "nearestBeatUpperBoundMissCount": 0,
            "medianBestErrorMilliseconds": None,
        },
        "error": {
            "code": "analyzed_track_not_found",
            "message": f"No analyzed-track artifact matched Rekordbox track key {match_key!r}",
        },
    }


def _summary(cases: Sequence[dict[str, Any]], *, top_k: int) -> dict[str, Any]:
    valid_cases = [case for case in cases if case.get("analyzedTrackPath")]
    reference_count = sum(int(case["metrics"]["referenceDropCount"]) for case in valid_cases)
    top1_hits = sum(int(case["metrics"]["top1HitCount"]) for case in valid_cases)
    topk_key = f"top{top_k}HitCount"
    topk_hits = sum(int(case["metrics"].get(topk_key, 0)) for case in valid_cases)
    nearest_beat_hits = sum(int(case["metrics"].get("nearestBeatUpperBoundHitCount", 0)) for case in valid_cases)
    errors = [
        float(match["bestErrorMilliseconds"])
        for case in valid_cases
        for match in case.get("matches", [])
        if match.get("matchedWithinTopK") and match.get("bestErrorMilliseconds") is not None
    ]
    return {
        "trackCount": len(cases),
        "matchedAnalyzedTrackCount": len(valid_cases),
        "missingAnalyzedTrackCount": len(cases) - len(valid_cases),
        "referenceDropCount": reference_count,
        "top1HitCount": top1_hits,
        f"top{top_k}HitCount": topk_hits,
        "nearestBeatUpperBoundHitCount": nearest_beat_hits,
        "top1Recall": _round_float(top1_hits / reference_count) if reference_count else 0.0,
        f"top{top_k}Recall": _round_float(topk_hits / reference_count) if reference_count else 0.0,
        "nearestBeatUpperBoundRecall": _round_float(nearest_beat_hits / reference_count) if reference_count else 0.0,
        "medianMatchedErrorMilliseconds": _round_optional(_median([abs(error) for error in errors])),
        "misses": [
            {
                "trackName": case["trackName"],
                "reference": match["reference"],
                "bestRank": match["bestRank"],
                "bestErrorMilliseconds": match["bestErrorMilliseconds"],
            }
            for case in valid_cases
            for match in case.get("matches", [])
            if not match.get("matchedWithinTopK")
        ],
        "nearestBeatUpperBoundMisses": [
            {
                "trackName": case["trackName"],
                "reference": match["reference"],
                "nearestBeatIndex": match["nearestBeatIndex"],
                "nearestBeatErrorMilliseconds": match["nearestBeatErrorMilliseconds"],
            }
            for case in valid_cases
            for match in case.get("nearestBeatUpperBoundMatches", [])
            if not match.get("matchedWithinTolerance")
        ],
    }


def _analyzed_artifact_index(analysis_root: Path) -> dict[str, Path]:
    tracks_root = analysis_root / "tracks"
    if not tracks_root.is_dir():
        raise DropAnchorBenchmarkError("analysis_root_invalid", f"Analysis root has no tracks directory: {analysis_root}")
    index: dict[str, Path] = {}
    for artifact_path in tracks_root.glob("*/analyzed-track.json"):
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        track_id = str(artifact.get("trackId") or artifact_path.parent.name)
        index[_safe_path_name(track_id)] = artifact_path
        source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
        source_uri = source.get("sourceUri") if isinstance(source.get("sourceUri"), str) else ""
        if source_uri:
            index[_safe_path_name(Path(source_uri).stem)] = artifact_path
    return index


def _track_match_key(track: RekordboxTrack) -> str:
    try:
        location_path = _coerce_local_path(_path_from_rekordbox_location(track.location))
        if location_path.stem:
            return _safe_path_name(location_path.stem)
    except DropAnchorBenchmarkError:
        pass
    return _safe_path_name(track.name)


def _drop_start_references(track: RekordboxTrack) -> tuple[DropStartReference, ...]:
    references = []
    for cue in track.cues:
        parsed = _parse_drop_start_cue(cue)
        if parsed is not None:
            references.append(parsed)
    return tuple(sorted(references, key=lambda reference: reference.time_seconds))


def _beat_grid_entries(artifact: dict[str, Any]) -> tuple[tuple[int | None, float], ...]:
    beat_grid = artifact.get("beatGrid") if isinstance(artifact.get("beatGrid"), dict) else {}
    beats = []
    for raw in beat_grid.get("beats") if isinstance(beat_grid.get("beats"), list) else []:
        if not isinstance(raw, dict):
            continue
        time_seconds = raw.get("timeSeconds")
        if not isinstance(time_seconds, int | float):
            continue
        beat_index = raw.get("index")
        beats.append((int(beat_index) if isinstance(beat_index, int) else None, float(time_seconds)))
    return tuple(sorted(beats, key=lambda beat: beat[1]))


def _parse_drop_start_cue(cue: RekordboxCue) -> DropStartReference | None:
    parsed = parse_semantic_cue_label(cue.name, provider_name="rekordbox")
    if parsed is None or parsed.section_type != "drop" or parsed.boundary != "start":
        return None
    reference_id = f"drop-start-{parsed.ordinal:03d}" if parsed.ordinal is not None else f"drop-start-{len(cue.name)}"
    return DropStartReference(
        id=reference_id,
        time_seconds=cue.start_seconds,
        cue_name=cue.name,
        ordinal=parsed.ordinal,
    )


def _path_from_rekordbox_location(location: str) -> Path:
    parsed = urlparse(location)
    if parsed.scheme != "file":
        raise DropAnchorBenchmarkError(
            "drop_anchor_benchmark_unsupported_location",
            f"Only file:// Rekordbox locations are supported: {location}",
        )
    path = unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:/", path):
        path = path[1:]
    return Path(path)


def _coerce_local_path(path: str | Path) -> Path:
    raw = str(path)
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", raw)
    if match and platform.system() != "Windows":
        drive = match.group(1).lower()
        remainder = match.group(2).replace("\\", "/")
        return Path(f"/mnt/{drive}/{remainder}")
    return Path(path)


def _safe_path_name(value: Any) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip()).strip("-._")
    return normalized.lower() or "track"


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _round_optional(value: float | None) -> float | None:
    return None if value is None else _round_float(value)


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
