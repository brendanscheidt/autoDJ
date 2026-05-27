"""Import Rekordbox XML tempo, beat grid, and cue metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import copy
import json
import math
from pathlib import Path
import re
from typing import Any, Callable
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlparse
import zlib

from .cache import write_json_atomic
from .semantic_cues import boundaries_from_named_cues, sections_and_cue_points_from_boundaries
from .tempo import normalize_dubstep_bpm


REKORDBOX_XML_BACKEND = "rekordbox.xml"
REKORDBOX_OVERRIDE_WARNING = (
    "Tempo, beat grid, sections, and cue points were overridden from Rekordbox XML metadata."
)
REKORDBOX_EXPORT_PRODUCT_VERSION = "7.2.11"


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
    tonality: str | None
    tempos: tuple[RekordboxTempo, ...]
    cues: tuple[RekordboxCue, ...]


def load_rekordbox_track(xml_path: str | Path, *, track_name: str | None = None) -> RekordboxTrack:
    """Load the first Rekordbox track, or the named track when provided."""

    path = Path(xml_path)
    tracks = load_rekordbox_tracks(path)

    if track_name:
        selected = next((track for track in tracks if track.name == track_name), None)
        if selected is None:
            raise RekordboxXmlError(
                "rekordbox_xml_track_not_found",
                f"Rekordbox XML did not contain a track named {track_name!r}",
            )
        return selected
    return tracks[0]


def load_rekordbox_tracks(xml_path: str | Path) -> tuple[RekordboxTrack, ...]:
    """Load all Rekordbox tracks from an XML export."""

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

    parsed_tracks: list[RekordboxTrack] = []
    for track in tracks:
        tempos = tuple(_parse_tempo(element) for element in track.findall("TEMPO"))
        if not tempos:
            raise RekordboxXmlError("rekordbox_xml_no_tempo", "Selected Rekordbox track has no TEMPO entries")

        cues = tuple(
            sorted(
                (_parse_cue(element) for element in track.findall("POSITION_MARK")),
                key=lambda cue: (cue.start_seconds, cue.num if cue.num is not None else math.inf),
            )
        )
        parsed_tracks.append(
            RekordboxTrack(
                name=track.get("Name", ""),
                location=track.get("Location", ""),
                average_bpm=_optional_float(track.get("AverageBpm")),
                tonality=track.get("Tonality"),
                tempos=tempos,
                cues=cues,
            )
        )
    return tuple(parsed_tracks)


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
    sections, cue_points = _sections_and_cues_from_rekordbox(rekordbox_track, tempo, duration_seconds)
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


def apply_rekordbox_semantic_overrides(
    analyzed_artifact: dict[str, Any],
    rekordbox_track: RekordboxTrack,
) -> dict[str, Any]:
    """Return an analyzed artifact with only Rekordbox semantic cues applied.

    This preserves the existing AutoDJ tempo, beat grid, and key analysis while
    replacing sections/cue points with manually labeled Rekordbox markers.
    """

    artifact = copy.deepcopy(analyzed_artifact)
    duration_seconds = float(artifact.get("durationSeconds") or 0.0)
    if duration_seconds <= 0:
        duration_seconds = _duration_from_cues_or_grid(rekordbox_track)

    beat_index_for_time = _beat_index_from_analyzed_artifact(artifact)
    sections, cue_points = _semantic_sections_and_cues_from_rekordbox(
        rekordbox_track,
        duration_seconds,
        beat_index_for_time=beat_index_for_time,
    )
    artifact["sections"] = sections
    artifact["cuePoints"] = cue_points

    source = artifact.setdefault("source", {})
    provider_metadata = source.setdefault("providerMetadata", {})
    provider_metadata["rekordboxSemanticXml"] = {
        "trackName": rekordbox_track.name,
        "location": rekordbox_track.location,
        "averageBpm": rekordbox_track.average_bpm,
        "preservedTempoBackend": artifact.get("tempo", {}).get("candidates", [{}])[0].get("backend"),
        "preservedBeatGridConfidence": artifact.get("beatGrid", {}).get("confidence"),
    }

    quality = artifact.setdefault("quality", {})
    warnings = list(quality.get("warnings") or [])
    semantic_warning = (
        "Rekordbox XML semantic cue labels were applied while preserving AutoDJ "
        "tempo, beat grid, and key analysis."
    )
    if semantic_warning not in warnings:
        warnings.insert(0, semantic_warning)
    quality["warnings"] = warnings

    analyzer = artifact.setdefault("analyzer", {})
    analyzer["rekordboxSemanticXmlAppliedAtUtc"] = (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )

    return artifact


def apply_rekordbox_semantic_xml_file(
    analyzed_path: str | Path,
    rekordbox_xml_path: str | Path,
    output_path: str | Path,
    *,
    track_name: str | None = None,
) -> Path:
    """Load analyzed JSON and Rekordbox XML, then write semantic-only overrides."""

    try:
        analyzed = json.loads(Path(analyzed_path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise RekordboxXmlError("analyzed_artifact_read_error", f"Could not read analyzed artifact: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RekordboxXmlError("analyzed_artifact_parse_error", f"Could not parse analyzed artifact JSON: {exc}") from exc
    if not isinstance(analyzed, dict):
        raise RekordboxXmlError("analyzed_artifact_invalid", "Analyzed artifact root must be a JSON object")

    rekordbox_track = load_rekordbox_track(rekordbox_xml_path, track_name=track_name)
    artifact = apply_rekordbox_semantic_overrides(analyzed, rekordbox_track)
    return write_json_atomic(output_path, artifact)


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


def export_analyzed_track_to_rekordbox_xml_file(
    analyzed_path: str | Path,
    output_path: str | Path,
    *,
    source_uri: str | None = None,
    track_name: str | None = None,
    include_cue_points: bool = False,
    cue_policy: str = "transition-8",
    max_hot_cues: int = 8,
    time_precision: int = 3,
) -> Path:
    """Export AutoDJ analyzed-track timing/section metadata as Rekordbox XML."""

    try:
        artifact = json.loads(Path(analyzed_path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise RekordboxXmlError("analyzed_artifact_read_error", f"Could not read analyzed artifact: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RekordboxXmlError("analyzed_artifact_parse_error", f"Could not parse analyzed artifact JSON: {exc}") from exc
    if not isinstance(artifact, dict):
        raise RekordboxXmlError("analyzed_artifact_invalid", "Analyzed artifact root must be a JSON object")

    xml_text = build_rekordbox_xml_from_analyzed_track(
        artifact,
        source_uri=source_uri,
        track_name=track_name,
        include_cue_points=include_cue_points,
        cue_policy=cue_policy,
        max_hot_cues=max_hot_cues,
        time_precision=time_precision,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(xml_text, encoding="utf-8")
    return output


def build_rekordbox_xml_from_analyzed_track(
    artifact: dict[str, Any],
    *,
    source_uri: str | None = None,
    track_name: str | None = None,
    include_cue_points: bool = False,
    cue_policy: str = "transition-8",
    max_hot_cues: int = 8,
    time_precision: int = 3,
) -> str:
    """Build a one-track Rekordbox XML document from an analyzed-track artifact."""

    if max_hot_cues <= 0:
        raise RekordboxXmlError("invalid_max_hot_cues", "max_hot_cues must be greater than zero")
    if time_precision < 0 or time_precision > 6:
        raise RekordboxXmlError("invalid_time_precision", "time_precision must be between 0 and 6")

    track_id = _string_or_default(artifact.get("trackId"), "autodj-track")
    name = track_name or _string_or_default(artifact.get("title"), track_id)
    tempo = artifact.get("tempo") if isinstance(artifact.get("tempo"), dict) else {}
    bpm = _positive_float(tempo.get("normalizedBpm")) or _positive_float(tempo.get("bpm"))
    if bpm is None:
        raise RekordboxXmlError("missing_tempo", "Analyzed artifact has no positive tempo bpm")

    duration_seconds = _positive_float(artifact.get("durationSeconds")) or _duration_from_artifact_boundaries(artifact)
    first_beat = _first_beat_seconds(artifact)
    location = _rekordbox_location(source_uri or _source_uri_from_artifact(artifact) or f"{track_id}.mp3")
    format_hint = _format_hint_from_uri(location)

    root = ET.Element("DJ_PLAYLISTS", {"Version": "1.0.0"})
    ET.SubElement(
        root,
        "PRODUCT",
        {"Name": "rekordbox", "Version": REKORDBOX_EXPORT_PRODUCT_VERSION, "Company": "AlphaTheta"},
    )
    collection = ET.SubElement(root, "COLLECTION", {"Entries": "1"})
    track = ET.SubElement(
        collection,
        "TRACK",
        {
            "TrackID": str(_stable_track_id(track_id)),
            "Name": name,
            "Artist": _string_or_default(artifact.get("artist"), ""),
            "Composer": "",
            "Album": _string_or_default(artifact.get("album"), ""),
            "Grouping": "",
            "Genre": _string_or_default(artifact.get("genre"), ""),
            "Kind": _kind_from_format(format_hint),
            "Size": "0",
            "TotalTime": str(max(0, round(duration_seconds))),
            "DiscNumber": "0",
            "TrackNumber": "0",
            "Year": "0",
            "AverageBpm": _format_decimal(bpm, 2),
            "DateAdded": datetime.now(UTC).date().isoformat(),
            "BitRate": "0",
            "SampleRate": "0",
            "Comments": "AutoDJ analyzed-track export",
            "PlayCount": "0",
            "Rating": "0",
            "Location": location,
            "Remixer": "",
            "Tonality": "",
            "Label": "",
            "Mix": "",
        },
    )
    ET.SubElement(
        track,
        "TEMPO",
        {
            "Inizio": _format_decimal(first_beat, time_precision),
            "Bpm": _format_decimal(bpm, 2),
            "Metro": "4/4",
            "Battito": "1",
        },
    )

    marks = _position_marks_from_artifact(
        artifact,
        include_cue_points=include_cue_points,
        cue_policy=cue_policy,
        max_hot_cues=max_hot_cues,
    )
    for index, mark in enumerate(marks):
        attrs = {
            "Name": mark["name"],
            "Type": "0",
            "Start": _format_decimal(mark["start"], time_precision),
            "Num": str(index),
            "Red": str(mark["color"]["red"]),
            "Green": str(mark["color"]["green"]),
            "Blue": str(mark["color"]["blue"]),
        }
        ET.SubElement(track, "POSITION_MARK", attrs)

    playlists = ET.SubElement(root, "PLAYLISTS")
    root_node = ET.SubElement(playlists, "NODE", {"Type": "0", "Name": "ROOT", "Count": "1"})
    ET.SubElement(root_node, "NODE", {"Name": "AutoDJ Export", "Type": "1", "KeyType": "0", "Entries": "0"})
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n\n' + ET.tostring(root, encoding="unicode") + "\n"


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
    duration_seconds: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return _semantic_sections_and_cues_from_rekordbox(
        rekordbox_track,
        duration_seconds,
        beat_index_for_time=lambda seconds: _beat_index(seconds, tempo),
    )


def _semantic_sections_and_cues_from_rekordbox(
    rekordbox_track: RekordboxTrack,
    duration_seconds: float,
    *,
    beat_index_for_time: Callable[[float], int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    named_boundaries = boundaries_from_named_cues(rekordbox_track.cues, provider_name="rekordbox")
    if named_boundaries:
        return sections_and_cue_points_from_boundaries(
            named_boundaries,
            duration_seconds=duration_seconds,
            provider_name=REKORDBOX_XML_BACKEND,
            beat_index_for_time=beat_index_for_time,
        )

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
                    "startBeatIndex": beat_index_for_time(start_cue.start_seconds),
                    "endBeatIndex": beat_index_for_time(end_cue.start_seconds),
                    "source": REKORDBOX_XML_BACKEND,
                }
            )

        cue_points.append(_cue_point_from_rekordbox_with_beat_index(start_cue, "drop", section_id, beat_index_for_time))
        if end_cue is not None:
            cue_points.append(_cue_point_from_rekordbox_with_beat_index(end_cue, "mix_out", section_id, beat_index_for_time))

    cue_points.sort(key=lambda cue: float(cue["timeSeconds"]))
    return sections, cue_points


def _cue_point_from_rekordbox(
    cue: RekordboxCue,
    cue_type: str,
    section_id: str,
    tempo: RekordboxTempo,
) -> dict[str, Any]:
    return _cue_point_from_rekordbox_with_beat_index(
        cue,
        cue_type,
        section_id,
        lambda seconds: _beat_index(seconds, tempo),
    )


def _cue_point_from_rekordbox_with_beat_index(
    cue: RekordboxCue,
    cue_type: str,
    section_id: str,
    beat_index_for_time: Callable[[float], int],
) -> dict[str, Any]:
    cue_point: dict[str, Any] = {
        "id": f"cue-rekordbox-{_cue_label(cue).lower()}",
        "type": cue_type,
        "timeSeconds": _round_float(cue.start_seconds),
        "sectionId": section_id,
        "confidence": 1.0,
        "tags": ["rekordbox_xml", f"hot_cue_{_cue_label(cue)}"],
        "beatIndex": beat_index_for_time(cue.start_seconds),
        "rekordboxNum": cue.num,
        "color": dict(cue.color),
    }
    if cue.name:
        cue_point["name"] = cue.name
    return cue_point


def _beat_index(time_seconds: float, tempo: RekordboxTempo) -> int:
    period_seconds = 60.0 / tempo.bpm
    return max(0, round((time_seconds - tempo.start_seconds) / period_seconds))


def _beat_index_from_analyzed_artifact(artifact: dict[str, Any]) -> Callable[[float], int]:
    beats = list(artifact.get("beatGrid", {}).get("beats") or [])
    indexed_times: list[tuple[int, float]] = []
    for fallback_index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            continue
        try:
            beat_time = float(beat["timeSeconds"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            beat_index = int(beat.get("index", fallback_index))
        except (TypeError, ValueError):
            beat_index = fallback_index
        indexed_times.append((beat_index, beat_time))

    indexed_times.sort(key=lambda item: item[1])
    if indexed_times:
        def nearest_beat_index(time_seconds: float) -> int:
            target = float(time_seconds)
            best_index, _ = min(indexed_times, key=lambda item: abs(item[1] - target))
            return max(0, best_index)

        return nearest_beat_index

    bpm = float(artifact.get("tempo", {}).get("normalizedBpm") or artifact.get("tempo", {}).get("bpm") or 0.0)
    period_seconds = 60.0 / bpm if bpm > 0 else 0.5

    def estimated_beat_index(time_seconds: float) -> int:
        return max(0, round(float(time_seconds) / period_seconds))

    return estimated_beat_index


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


def _position_marks_from_artifact(
    artifact: dict[str, Any],
    *,
    include_cue_points: bool,
    cue_policy: str,
    max_hot_cues: int,
) -> list[dict[str, Any]]:
    marks: list[dict[str, Any]] = []
    section_counts: dict[str, int] = {}
    seen: set[tuple[str, float]] = set()
    for section in artifact.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_type = _string_or_default(section.get("type"), "section")
        section_counts[section_type] = section_counts.get(section_type, 0) + 1
        ordinal = section_counts[section_type]
        start = _positive_or_zero_float(section.get("startSeconds"))
        end = _positive_or_zero_float(section.get("endSeconds"))
        if start is not None:
            _add_mark(
                marks,
                seen,
                name=f"{section_type}_{ordinal}_start",
                start=start,
                color=_color_for_section(section_type),
            )
        if end is not None and start is not None and end > start:
            _add_mark(
                marks,
                seen,
                name=f"{section_type}_{ordinal}_end",
                start=end,
                color=_darker_color(_color_for_section(section_type)),
            )

    if include_cue_points:
        cue_counts: dict[str, int] = {}
        for cue in artifact.get("cuePoints", []):
            if not isinstance(cue, dict):
                continue
            cue_type = _string_or_default(cue.get("type"), "cue")
            cue_counts[cue_type] = cue_counts.get(cue_type, 0) + 1
            start = _positive_or_zero_float(cue.get("timeSeconds"))
            if start is None:
                continue
            _add_mark(
                marks,
                seen,
                name=_string_or_default(cue.get("name"), f"cue_{cue_type}_{cue_counts[cue_type]}"),
                start=start,
                color=_color_for_section(cue_type),
            )
    marks = sorted(marks, key=lambda mark: (mark["start"], mark["name"]))
    if cue_policy == "all":
        return marks
    if cue_policy == "transition-8":
        return _select_transition_hot_cues(marks, max_hot_cues)
    raise RekordboxXmlError(
        "invalid_cue_policy",
        "cue_policy must be 'transition-8' or 'all'",
    )


def _select_transition_hot_cues(marks: list[dict[str, Any]], max_hot_cues: int) -> list[dict[str, Any]]:
    selected = sorted(
        marks,
        key=lambda mark: (-_transition_hotcue_priority(str(mark["name"])), float(mark["start"]), str(mark["name"])),
    )[:max_hot_cues]
    return sorted(selected, key=lambda mark: (float(mark["start"]), str(mark["name"])))


def _transition_hotcue_priority(name: str) -> int:
    match = re.match(r"^(?P<section>[a-z_]+)_(?P<number>\d+)_(?P<edge>start|end)$", name)
    if not match:
        return 0
    section = match.group("section")
    number = int(match.group("number"))
    edge = match.group("edge")
    if section == "drop" and edge == "start":
        return 300 - number
    if section == "build" and edge == "start":
        return 260 - number
    if section == "drop" and edge == "end":
        return 240 - number
    if section == "break" and edge == "start":
        return 130 - number
    if section == "outro" and edge == "start":
        return 120 - number
    if section == "intro" and edge == "start":
        return 80 - number
    return 10


def _add_mark(
    marks: list[dict[str, Any]],
    seen: set[tuple[str, float]],
    *,
    name: str,
    start: float,
    color: dict[str, int],
) -> None:
    key = (name, round(start, 3))
    if key in seen:
        return
    seen.add(key)
    marks.append({"name": name, "start": start, "color": color})


def _color_for_section(section_type: str) -> dict[str, int]:
    colors = {
        "intro": {"red": 90, "green": 160, "blue": 255},
        "verse": {"red": 69, "green": 172, "blue": 219},
        "break": {"red": 125, "green": 193, "blue": 61},
        "build": {"red": 255, "green": 194, "blue": 66},
        "drop": {"red": 255, "green": 55, "blue": 111},
        "outro": {"red": 170, "green": 114, "blue": 255},
        "mix_out": {"red": 170, "green": 114, "blue": 255},
    }
    return dict(colors.get(section_type, {"red": 210, "green": 210, "blue": 210}))


def _darker_color(color: dict[str, int]) -> dict[str, int]:
    return {channel: max(0, round(value * 0.7)) for channel, value in color.items()}


def _first_beat_seconds(artifact: dict[str, Any]) -> float:
    beat_grid = artifact.get("beatGrid") if isinstance(artifact.get("beatGrid"), dict) else {}
    beats = beat_grid.get("beats") if isinstance(beat_grid.get("beats"), list) else []
    for beat in beats:
        if isinstance(beat, dict):
            value = _positive_or_zero_float(beat.get("timeSeconds"))
            if value is not None:
                return value
    return 0.0


def _duration_from_artifact_boundaries(artifact: dict[str, Any]) -> float:
    values: list[float] = []
    for field in ("sections", "cuePoints"):
        for item in artifact.get(field, []):
            if not isinstance(item, dict):
                continue
            for key in ("startSeconds", "endSeconds", "timeSeconds"):
                value = _positive_or_zero_float(item.get(key))
                if value is not None:
                    values.append(value)
    return max(values, default=0.0)


def _source_uri_from_artifact(artifact: dict[str, Any]) -> str | None:
    source = artifact.get("source")
    if not isinstance(source, dict):
        return None
    for key in ("sourceUri", "uri", "path"):
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    provider = source.get("providerMetadata")
    if isinstance(provider, dict):
        value = provider.get("sourceUri")
        if isinstance(value, str) and value:
            return value
    return None


def _rekordbox_location(source_uri: str) -> str:
    if source_uri.startswith("file://"):
        return source_uri
    normalized = source_uri.replace("\\", "/")
    if normalized.startswith("/mnt/") and len(normalized) > 6 and normalized[5].isalpha() and normalized[6] == "/":
        normalized = f"{normalized[5].upper()}:{normalized[6:]}"
    if len(normalized) > 2 and normalized[1] == ":":
        return "file://localhost/" + quote(normalized, safe="/:")
    path = Path(source_uri)
    if path.is_absolute():
        return path.as_uri()
    return "file://localhost/" + quote(normalized, safe="/:")


def _format_hint_from_uri(source_uri: str) -> str:
    parsed = urlparse(source_uri)
    suffix = Path(parsed.path).suffix.lstrip(".").lower()
    return suffix or "unknown"


def _kind_from_format(format_hint: str) -> str:
    labels = {
        "mp3": "MP3 File",
        "wav": "WAV File",
        "flac": "FLAC File",
        "aiff": "AIFF File",
        "aif": "AIFF File",
        "m4a": "M4A File",
    }
    return labels.get(format_hint.lower(), "Audio File")


def _stable_track_id(track_id: str) -> int:
    return zlib.crc32(track_id.encode("utf-8")) & 0x7FFFFFFF


def _format_decimal(value: float, digits: int) -> str:
    return f"{float(value):.{digits}f}"


def _string_or_default(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _positive_float(value: Any) -> float | None:
    if isinstance(value, int | float) and float(value) > 0.0:
        return float(value)
    return None


def _positive_or_zero_float(value: Any) -> float | None:
    if isinstance(value, int | float) and float(value) >= 0.0:
        return float(value)
    return None
