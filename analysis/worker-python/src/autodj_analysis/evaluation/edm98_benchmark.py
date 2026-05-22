"""Benchmark EDM-98 / EDMFormer section predictions against Rekordbox drop cues."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..cache import SCHEMA_VERSION, write_json_atomic
from ..edm98 import Edm98Options, Edm98Predictor, edm98_segments_to_drop_candidates
from ..rekordbox_xml import RekordboxTrack, RekordboxXmlError, load_rekordbox_tracks
from .cue_detr_benchmark import snap_cue_candidates_to_beat_grid
from .drop_anchor_benchmark import (
    DropAnchorBenchmarkError,
    DropStartReference,
    _analyzed_artifact_index,
    _beat_grid_entries,
    _coerce_local_path,
    _drop_start_references,
    _path_from_rekordbox_location,
    _reference_match,
    _safe_path_name,
)


EDM98_DROP_BENCHMARK_REPORT_TYPE = "edm98-drop-anchor-benchmark"
DEFAULT_EDM98_DROP_TOP_K = 3
DEFAULT_EDM98_DROP_MATCH_TOLERANCE_SECONDS = 0.35
DEFAULT_EDM98_SNAP_WINDOW_SECONDS = 0.75


def run_edm98_drop_benchmark(
    rekordbox_xml_path: str | Path,
    output_root: str | Path,
    *,
    analysis_root: str | Path | None = None,
    top_k: int = DEFAULT_EDM98_DROP_TOP_K,
    match_tolerance_seconds: float = DEFAULT_EDM98_DROP_MATCH_TOLERANCE_SECONDS,
    snap_window_seconds: float = DEFAULT_EDM98_SNAP_WINDOW_SECONDS,
    edm98_options: Edm98Options | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run EDMFormer over Rekordbox tracks and compare drop candidates."""

    if top_k <= 0:
        raise DropAnchorBenchmarkError("invalid_top_k", "top_k must be greater than zero")
    if match_tolerance_seconds <= 0:
        raise DropAnchorBenchmarkError("invalid_match_tolerance", "match_tolerance_seconds must be greater than zero")
    if snap_window_seconds < 0:
        raise DropAnchorBenchmarkError("invalid_snap_window", "snap_window_seconds must be zero or greater")
    if limit is not None and limit <= 0:
        raise DropAnchorBenchmarkError("invalid_limit", "limit must be greater than zero when provided")

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        tracks = load_rekordbox_tracks(rekordbox_xml_path)
    except RekordboxXmlError as exc:
        raise DropAnchorBenchmarkError(exc.code, exc.message) from exc
    if limit is not None:
        tracks = tracks[:limit]

    analyzed_index = _analyzed_artifact_index(Path(analysis_root)) if analysis_root is not None else {}
    predictor = Edm98Predictor(edm98_options)
    cases = [
        _run_case(
            track,
            predictor,
            analyzed_index,
            output_root,
            top_k=top_k,
            match_tolerance_seconds=match_tolerance_seconds,
            snap_window_seconds=snap_window_seconds,
        )
        for track in tracks
    ]
    summary = {
        "schemaVersion": SCHEMA_VERSION,
        "reportType": EDM98_DROP_BENCHMARK_REPORT_TYPE,
        "createdAtUtc": _utc_now_iso(),
        "rekordboxXmlPath": str(rekordbox_xml_path),
        "analysisRoot": str(analysis_root) if analysis_root is not None else None,
        "outputRoot": str(output_root),
        "parameters": {
            "topK": top_k,
            "matchToleranceSeconds": match_tolerance_seconds,
            "snapWindowSeconds": snap_window_seconds,
            "limit": limit,
            "edm98": _options_payload(edm98_options or Edm98Options()),
        },
        "cases": cases,
        "summary": _summary(cases, top_k=top_k),
    }
    write_json_atomic(output_root / "edm98-drop-benchmark-summary.json", summary)
    return summary


def _run_case(
    track: RekordboxTrack,
    predictor: Edm98Predictor,
    analyzed_index: dict[str, Path],
    output_root: Path,
    *,
    top_k: int,
    match_tolerance_seconds: float,
    snap_window_seconds: float,
) -> dict[str, Any]:
    references = _drop_start_references(track)
    case_name = _safe_path_name(track.name)
    case_dir = output_root / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    try:
        audio_path = _coerce_local_path(_path_from_rekordbox_location(track.location))
    except DropAnchorBenchmarkError as exc:
        return _error_case(track, references, exc.code, exc.message)
    if not audio_path.is_file():
        return _error_case(track, references, "audio_not_found", f"Audio file does not exist: {audio_path}")

    prediction = predictor.predict(audio_path)
    prediction_path = write_json_atomic(case_dir / "edm98-sections.json", prediction)
    beat_grid = _beat_grid_for_track(track, analyzed_index)
    candidates = snap_cue_candidates_to_beat_grid(
        edm98_segments_to_drop_candidates(prediction["segments"]),
        beat_grid,
        snap_window_seconds=snap_window_seconds,
    )
    candidates_path = write_json_atomic(
        case_dir / "edm98-drop-candidates.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "artifact": "edm98-drop-candidates",
            "trackName": track.name,
            "predictionPath": str(prediction_path),
            "snapWindowSeconds": snap_window_seconds,
            "beatGridAvailable": bool(beat_grid),
            "candidates": candidates,
        },
    )
    matches = [
        _reference_match(reference, candidates, top_k=top_k, tolerance_seconds=match_tolerance_seconds)
        for reference in references
    ]
    return {
        "trackName": track.name,
        "audioPath": str(audio_path),
        "predictionPath": str(prediction_path),
        "candidatePath": str(candidates_path),
        "referenceDropStarts": [reference.to_dict() for reference in references],
        "topCandidates": candidates[:top_k],
        "matches": matches,
        "metrics": _case_metrics(matches, references, top_k=top_k),
    }


def _beat_grid_for_track(track: RekordboxTrack, analyzed_index: dict[str, Path]) -> tuple[tuple[int | None, float], ...]:
    if not analyzed_index:
        return ()
    artifact_path = analyzed_index.get(_safe_path_name(Path(_coerce_local_path(_path_from_rekordbox_location(track.location))).stem))
    if artifact_path is None:
        artifact_path = analyzed_index.get(_safe_path_name(track.name))
    if artifact_path is None:
        return ()
    try:
        import json

        artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ()
    return _beat_grid_entries(artifact)


def _error_case(
    track: RekordboxTrack,
    references: Sequence[DropStartReference],
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "trackName": track.name,
        "audioPath": None,
        "predictionPath": None,
        "candidatePath": None,
        "referenceDropStarts": [reference.to_dict() for reference in references],
        "topCandidates": [],
        "matches": [],
        "metrics": {
            "referenceDropCount": 0,
            "top1HitCount": 0,
            "top3HitCount": 0,
            "missingWithinTopKCount": 0,
            "medianBestErrorMilliseconds": None,
        },
        "error": {"code": code, "message": message},
    }


def _case_metrics(
    matches: Sequence[dict[str, Any]],
    references: Sequence[DropStartReference],
    *,
    top_k: int,
) -> dict[str, Any]:
    errors = [
        abs(float(match["bestErrorMilliseconds"]))
        for match in matches
        if match.get("matchedWithinTopK") and match.get("bestErrorMilliseconds") is not None
    ]
    return {
        "referenceDropCount": len(references),
        "top1HitCount": sum(1 for match in matches if match["matchedWithinTop1"]),
        f"top{top_k}HitCount": sum(1 for match in matches if match["matchedWithinTopK"]),
        "missingWithinTopKCount": sum(1 for match in matches if not match["matchedWithinTopK"]),
        "medianBestErrorMilliseconds": _round_optional(_median(errors)),
    }


def _summary(cases: Sequence[dict[str, Any]], *, top_k: int) -> dict[str, Any]:
    valid_cases = [case for case in cases if not case.get("error")]
    reference_count = sum(int(case["metrics"]["referenceDropCount"]) for case in valid_cases)
    top1_hits = sum(int(case["metrics"]["top1HitCount"]) for case in valid_cases)
    topk_key = f"top{top_k}HitCount"
    topk_hits = sum(int(case["metrics"].get(topk_key, 0)) for case in valid_cases)
    errors = [
        float(match["bestErrorMilliseconds"])
        for case in valid_cases
        for match in case.get("matches", [])
        if match.get("matchedWithinTopK") and match.get("bestErrorMilliseconds") is not None
    ]
    return {
        "trackCount": len(cases),
        "validTrackCount": len(valid_cases),
        "errorTrackCount": len(cases) - len(valid_cases),
        "referenceDropCount": reference_count,
        "top1HitCount": top1_hits,
        f"top{top_k}HitCount": topk_hits,
        "top1Recall": _round_float(top1_hits / reference_count) if reference_count else 0.0,
        f"top{top_k}Recall": _round_float(topk_hits / reference_count) if reference_count else 0.0,
        "medianMatchedErrorMilliseconds": _round_optional(_median([abs(error) for error in errors])),
        "misses": [
            {
                "trackName": case["trackName"],
                "reference": match["reference"],
                "bestRank": match["bestRank"],
                "bestCandidateTimeSeconds": match["bestCandidateTimeSeconds"],
                "bestErrorMilliseconds": match["bestErrorMilliseconds"],
            }
            for case in valid_cases
            for match in case.get("matches", [])
            if not match["matchedWithinTopK"]
        ],
    }


def _options_payload(options: Edm98Options) -> dict[str, Any]:
    return {
        "checkpoint": options.checkpoint,
        "config": options.config,
        "musicfmStat": options.musicfm_stat,
        "musicfmModel": options.musicfm_model,
        "device": options.device,
        "lowMemory": options.low_memory,
        "hfCacheDir": options.hf_cache_dir,
        "offline": options.offline,
        "noCache": options.no_cache,
    }


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _round_optional(value: float | None) -> float | None:
    if value is None:
        return None
    return _round_float(value)


def _round_float(value: float) -> float:
    return round(float(value), 6)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
