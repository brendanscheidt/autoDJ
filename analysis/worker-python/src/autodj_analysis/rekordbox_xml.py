"""Import Rekordbox XML tempo, beat grid, and cue metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import copy
import json
import math
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .cache import write_json_atomic
from .tempo import normalize_dubstep_bpm


REKORDBOX_XML_BACKEND = "rekordbox.xml"
REKORDBOX_OVERRIDE_WARNING = (
    "Tempo, beat grid, sections, and cue points were overridden from Rekordbox XML metadata."
)


class RekordboxXmlError(ValueError):
    """Expected Rekordbox XML import failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class RekordboxTempo:
    start_seconds: float
    bpm: float
    meter: str
    beat: int


@dataclass(frozen=True)
class RekordboxCue:
    start_seconds: float
    num: int | None
    name: str
    color: dict[str, int]


@dataclass(frozen=True)
class RekordboxTrack:
    name: str
    location: str
    average_bpm: float | None
    tempos: tuple[RekordboxTempo, ...]
    cues: tuple[RekordboxCue, ...]


def load_rekordbox_track(xml_path: str | Path, *, track_name: str | None = None) -> RekordboxTrack:
    """Load the first Rekordbox track, or the named track when provided."""

    path = Path(xml_path)
    try:
        root = ET.parse(path).getroot()
    except OSError as exc:
        raise RekordboxXmlError("rekordbox_xml_read_error", f"Could not read Rekordbox XML: {exc}") from exc
    except ET.ParseError as exc:
        raise RekordboxXmlError("rekordbox_xml_parse_error", f"Could not parse Rekordbox XML: {exc}") from exc

    tracks = list(root.findall(".//TRACK"))
    if not tracks:
        raise RekordboxXmlError("rekordbox_xml_no_tracks", "Rekordbox XML did not contain any TRACK entries")

    selected = None
    if track_name:
        selected = next((track for track in tracks if track.get("Name") == track_name), None)
        if selected is None:
            raise RekordboxXmlError(
                "rekordbox_xml_track_not_found",
                f"Rekordbox XML did not contain a track named {track_name!r}",
            )
    else:
        selected = tracks[0]

    tempos = tuple(_parse_tempo(element) for element in selected.findall("TEMPO"))
    if not tempos:
        raise RekordboxXmlError("rekordbox_xml_no_tempo", "Selected Rekordbox track has no TEMPO entries")

    cues = tuple(
        sorted(
            (_parse_cue(element) for element in selected.findall("POSITION_MARK")),
            key=lambda cue: (cue.start_seconds, cue.num if cue.num is not None else math.inf),
        )
    )
    return RekordboxTrack(
        name=selected.get("Name", ""),
        location=selected.get("Location", ""),
        average_bpm=_optional_float(selected.get("AverageBpm")),
        tempos=tempos,
        cues=cues,
    )


def apply_rekordbox_overrides(
    analyzed_artifact: dict[str, Any],
    rekordbox_track: RekordboxTrack,
) -> dict[str, Any]:
    """Return an analyzed artifact with Rekordbox grid and cue overrides applied."""

    if not rekordbox_track.tempos:
        raise RekordboxXmlError("rekordbox_xml_no_tempo", "Rekordbox track has no tempo marker")
    tempo = rekordbox_track.tempos[0]
    if tempo.bpm <= 0:
        raise RekordboxXmlError("rekordbox_xml_invalid_tempo", "Rekordbox BPM must be greater than zero")

    artifact = copy.deepcopy(analyzed_artifact)
    duration_seconds = float(artifact.get("durationSeconds") or 0.0)
    if duration_seconds <= 0:
        duration_seconds = _duration_from_cues_or_grid(rekordbox_track)

    normalized = normalize_dubstep_bpm(tempo.bpm)
    previous_candidates = artifact.get("tempo", {}).get("candidates", [])
    artifact["tempo"] = {
        "bpm": _round_float(tempo.bpm),
        "normalizedBpm": normalized.normalized_bpm,
        "confidence": 1.0,
        "tempoClass": normalized.tempo_class,
        "candidates": [
            {
                "bpm": _round_float(tempo.bpm),
                "confidence": 1.0,
                "backend": REKORDBOX_XML_BACKEND,
            },
            *[dict(candidate) for candidate in previous_candidates],
        ],
    }
    artifact["beatGrid"] = {
        "beats": _build_rekordbox_beats(tempo, duration_seconds),
        "downbeats": [],
        "confidence": 1.0,
    }
    sections, cue_points = _sections_and_cues_from_rekordbox(rekordbox_track, tempo)
    artifact["sections"] = sections
    artifact["cuePoints"] = cue_points

    source = artifact.setdefault("source", {})
    provider_metadata = source.setdefault("providerMetadata", {})
    provider_metadata["rekordboxXml"] = {
        "trackName": rekordbox_track.name,
        "location": rekordbox_track.location,
        "averageBpm": rekordbox_track.average_bpm,
        "tempoStartSeconds": _round_float(tempo.start_seconds),
        "tempoBpm": _round_float(tempo.bpm),
    }

    quality = artifact.setdefault("quality", {})
    quality["overallConfidence"] = max(float(quality.get("overallConfidence") or 0.0), 0.95)
    warnings = list(quality.get("warnings") or [])
    if REKORDBOX_OVERRIDE_WARNING not in warnings:
        warnings.insert(0, REKORDBOX_OVERRIDE_WARNING)
    quality["warnings"] = warnings

    analyzer = artifact.setdefault("analyzer", {})
    analyzer["rekordboxXmlAppliedAtUtc"] = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return artifact


def apply_rekordbox_xml_file(
    analyzed_path: str | Path,
    rekordbox_xml_path: str | Path,
    output_path: str | Path,
    *,
    track_name: str | None = None,
) -> Path:
    """Load an analyzed artifact and Rekordbox XML, then write an overridden artifact."""

    try:
        analyzed = json.loads(Path(analyzed_path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise RekordboxXmlError("analyzed_artifact_read_error", f"Could not read analyzed artifact: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RekordboxXmlError("analyzed_artifact_parse_error", f"Could not parse analyzed artifact JSON: {exc}") from exc
    if not isinstance(analyzed, dict):
        raise RekordboxXmlError("analyzed_artifact_invalid", "Analyzed artifact root must be a JSON object")

    rekordbox_track = load_rekordbox_track(rekordbox_xml_path, track_name=track_name)
    artifact = apply_rekordbox_overrides(analyzed, rekordbox_track)
    return write_json_atomic(output_path, artifact)


def _parse_tempo(element: ET.Element) -> RekordboxTempo:
    return RekordboxTempo(
        start_seconds=_required_float(element, "Inizio", "TEMPO"),
        bpm=_required_float(element, "Bpm", "TEMPO"),
        meter=element.get("Metro", ""),
        beat=int(_required_float(element, "Battito", "TEMPO")),
    )


def _parse_cue(element: ET.Element) -> RekordboxCue:
    return RekordboxCue(
        start_seconds=_required_float(element, "Start", "POSITION_MARK"),
        num=_optional_int(element.get("Num")),
        name=element.get("Name", ""),
        color={
            "red": _optional_int(element.get("Red")) or 0,
            "green": _optional_int(element.get("Green")) or 0,
            "blue": _optional_int(element.get("Blue")) or 0,
        },
    )


def _build_rekordbox_beats(tempo: RekordboxTempo, duration_seconds: float) -> list[dict[str, float | int]]:
    period_seconds = 60.0 / tempo.bpm
    beat_count = max(0, int(math.floor((duration_seconds - tempo.start_seconds + 1e-9) / period_seconds)) + 1)
    return [
        {
            "index": index,
            "timeSeconds": _round_float(tempo.start_seconds + index * period_seconds),
            "confidence": 1.0,
        }
        for index in range(beat_count)
        if tempo.start_seconds + index * period_seconds <= duration_seconds + 1e-6
    ]


def _sections_and_cues_from_rekordbox(
    rekordbox_track: RekordboxTrack,
    tempo: RekordboxTempo,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cues = list(rekordbox_track.cues)
    sections: list[dict[str, Any]] = []
    cue_points: list[dict[str, Any]] = []

    for pair_index in range(0, len(cues), 2):
        start_cue = cues[pair_index]
        end_cue = cues[pair_index + 1] if pair_index + 1 < len(cues) else None
        section_number = len(sections) + 1
        section_id = f"section-rekordbox-drop-{section_number:03d}"

        if end_cue is not None and end_cue.start_seconds > start_cue.start_seconds:
            sections.append(
                {
                    "id": section_id,
                    "type": "drop",
                    "startSeconds": _round_float(start_cue.start_seconds),
                    "endSeconds": _round_float(end_cue.start_seconds),
                    "confidence": 1.0,
                    "startBeatIndex": _beat_index(start_cue.start_seconds, tempo),
                    "endBeatIndex": _beat_index(end_cue.start_seconds, tempo),
                    "source": REKORDBOX_XML_BACKEND,
                }
            )

        cue_points.append(_cue_point_from_rekordbox(start_cue, "drop", section_id, tempo))
        if end_cue is not None:
            cue_points.append(_cue_point_from_rekordbox(end_cue, "mix_out", section_id, tempo))

    cue_points.sort(key=lambda cue: float(cue["timeSeconds"]))
    return sections, cue_points


def _cue_point_from_rekordbox(
    cue: RekordboxCue,
    cue_type: str,
    section_id: str,
    tempo: RekordboxTempo,
) -> dict[str, Any]:
    cue_point: dict[str, Any] = {
        "id": f"cue-rekordbox-{_cue_label(cue).lower()}",
        "type": cue_type,
        "timeSeconds": _round_float(cue.start_seconds),
        "sectionId": section_id,
        "confidence": 1.0,
        "tags": ["rekordbox_xml", f"hot_cue_{_cue_label(cue)}"],
        "beatIndex": _beat_index(cue.start_seconds, tempo),
        "rekordboxNum": cue.num,
        "color": dict(cue.color),
    }
    if cue.name:
        cue_point["name"] = cue.name
    return cue_point


def _beat_index(time_seconds: float, tempo: RekordboxTempo) -> int:
    period_seconds = 60.0 / tempo.bpm
    return max(0, round((time_seconds - tempo.start_seconds) / period_seconds))


def _cue_label(cue: RekordboxCue) -> str:
    if cue.num is None or cue.num < 0:
        return "unknown"
    return chr(ord("A") + cue.num) if cue.num < 26 else str(cue.num)


def _duration_from_cues_or_grid(rekordbox_track: RekordboxTrack) -> float:
    cue_end = max((cue.start_seconds for cue in rekordbox_track.cues), default=0.0)
    tempo_start = rekordbox_track.tempos[0].start_seconds if rekordbox_track.tempos else 0.0
    return max(cue_end, tempo_start)


def _required_float(element: ET.Element, attribute: str, element_name: str) -> float:
    value = _optional_float(element.get(attribute))
    if value is None:
        raise RekordboxXmlError(
            "rekordbox_xml_missing_field",
            f"{element_name} is missing required numeric attribute {attribute!r}",
        )
    return value


def _optional_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _round_float(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded
