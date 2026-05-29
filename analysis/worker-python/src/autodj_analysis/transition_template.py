"""Parse hand-authored transition sheets into recipe or MixPlan JSON."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from .cache import write_json_atomic


class TransitionTemplateError(ValueError):
    """Expected transition-sheet parse failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class TransitionTemplateResult:
    artifact: str
    output_path: Path
    template_path: Path
    family: str
    transition_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "artifact": self.artifact,
            "outputPath": str(self.output_path),
            "templatePath": str(self.template_path),
            "family": self.family,
            "transitionId": self.transition_id,
        }


@dataclass(frozen=True)
class _Action:
    deck: str
    control: str
    when: str
    value: float
    interpolation: str


@dataclass(frozen=True)
class _DeckTiming:
    deck_id: str
    track_id: str
    source_uri: str
    source_start_seconds: float
    source_end_seconds: float
    timeline_start_seconds: float
    timeline_end_seconds: float
    first_beat_seconds: float


_ACTION_RE = re.compile(
    r"^(?P<deck>[abAB])\.(?P<control>[A-Za-z][A-Za-z0-9_]*)\s+"
    r"at\s+(?P<when>.+?)\s*=\s*(?P<value>[-+]?\d+(?:\.\d+)?)"
    r"(?:\s+(?P<interpolation>[A-Za-z][A-Za-z0-9_]*))?$"
)


def parse_transition_template_file(template_path: str | Path, output_path: str | Path) -> TransitionTemplateResult:
    """Parse a transition sheet and write canonical JSON output."""

    path = Path(template_path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise TransitionTemplateError("template_read_error", f"Could not read transition sheet: {exc}") from exc

    template = _parse_transition_sheet(text)
    fields = _fields(template)
    kind = _required_field(fields, "kind")
    if kind == "specific_transition":
        payload = build_mix_plan_from_template(template)
        artifact = "mix-plan"
        family = _transition_family(fields)
        transition_id = str(payload["transitions"][0]["transitionId"])
    elif kind == "generic_transition":
        payload = build_recipe_from_template(template)
        artifact = "transition-recipe"
        family = str(payload["transitionFamily"])
        transition_id = str(payload["recipeId"])
    else:
        raise TransitionTemplateError(
            "unsupported_template_kind",
            "Transition sheet kind must be 'specific_transition' or 'generic_transition'",
        )

    output = write_json_atomic(output_path, payload)
    return TransitionTemplateResult(
        artifact=artifact,
        output_path=output,
        template_path=path,
        family=family,
        transition_id=transition_id,
    )


def build_mix_plan_from_template(template: dict[str, Any]) -> dict[str, Any]:
    """Build a concrete MixPlan from a parsed specific transition sheet."""

    fields = _fields(template)
    actions = _actions(template)
    family = _transition_family(fields)
    bpm = _bpm(fields)
    beats_per_bar = _beats_per_bar(fields)
    measure_seconds = beats_per_bar * 60.0 / bpm

    if family == "drop_switch":
        timings, transition, source_anchors = _drop_switch_context(fields, bpm=bpm, beats_per_bar=beats_per_bar)
    elif family == "reverb_exit":
        timings, transition, source_anchors = _reverb_exit_context(fields, bpm=bpm, beats_per_bar=beats_per_bar)
    else:
        raise TransitionTemplateError(
            "unsupported_transition_type",
            "Specific transition type must be 'drop_switch' or 'reverb_exit'",
        )

    deck_a = timings["a"]
    deck_b = timings["b"]
    commands = [
        {
            "type": "load",
            "at": _round(deck_a.timeline_start_seconds),
            "deck": 1,
            "trackId": deck_a.track_id,
            "stem": "full",
            "cueSeconds": _round(deck_a.source_start_seconds),
        },
        {"type": "play", "at": _round(deck_a.timeline_start_seconds), "deck": 1},
        {
            "type": "load",
            "at": _round(deck_b.timeline_start_seconds),
            "deck": 2,
            "trackId": deck_b.track_id,
            "stem": "full",
            "cueSeconds": _round(deck_b.source_start_seconds),
        },
        {"type": "play", "at": _round(deck_b.timeline_start_seconds), "deck": 2},
    ]
    commands.extend(_automation_commands(actions, timings, bpm=bpm, beats_per_bar=beats_per_bar))
    commands.sort(key=lambda command: float(command.get("at", 0.0)))

    transition["sourceAnchors"] = source_anchors
    transition.setdefault("measureCountToTarget", _round((transition["timelineEndSeconds"] - transition["timelineStartSeconds"]) / measure_seconds))

    notes = _field(fields, "notes", f"Manual {family} transition sheet")
    return {
        "schemaVersion": "1.0.0",
        "planId": _field(fields, "plan_id", f"manual-plan-{_timestamp_id()}"),
        "createdAtUtc": _now(),
        "strategy": {
            "strategyId": "manual-transition-sheet",
            "strategyVersion": "1.0.0",
            "templatePath": _field(fields, "template_path", ""),
            "bpm": _round(bpm),
            "beatsPerBar": beats_per_bar,
        },
        "assets": [_asset(deck_a), _asset(deck_b)],
        "tracks": [_placement(deck_a), _placement(deck_b)],
        "transitions": [transition],
        "commands": commands,
        "annotations": [
            {
                "at": _round(float(transition["timelineStartSeconds"])),
                "transitionId": transition["transitionId"],
                "message": notes,
            }
        ],
    }


def build_recipe_from_template(template: dict[str, Any]) -> dict[str, Any]:
    """Build a reusable transition recipe from a parsed generic transition sheet."""

    fields = _fields(template)
    family = _transition_family(fields)
    requirements = list(template.get("requirements", []))
    anchors = dict(template.get("anchors", {}))
    automation: dict[str, dict[str, list[dict[str, object]]]] = {"a": {}, "b": {}}
    for action in _actions(template):
        automation[action.deck].setdefault(action.control, []).append(
            {
                "timeExpression": action.when,
                "value": action.value,
                "interpolation": action.interpolation,
            }
        )

    exact_bpm = _bool_field(fields, "exact_bpm_required", default=("same_bpm" in requirements or "exact_bpm" in requirements))
    return {
        "schemaVersion": "1.0.0",
        "artifact": "transition-recipe",
        "recipeId": _field(fields, "recipe_id", _field(fields, "name", f"recipe-{family}-{_timestamp_id()}")),
        "createdAtUtc": _now(),
        "transitionFamily": family,
        "semanticRequirements": {
            "exactBpmRequired": exact_bpm,
            "camelotKeyCompatibility": _field(fields, "camelot_key_compatibility", "placeholder"),
            "requirements": requirements,
            "anchors": anchors,
            "energyNotes": _field(fields, "energy_notes", ""),
            "humanNotes": _field(fields, "notes", ""),
        },
        "automation": automation,
    }


def _parse_transition_sheet(text: str) -> dict[str, Any]:
    fields: dict[str, str] = {}
    requirements: list[str] = []
    anchors: dict[str, str] = {}
    actions: list[_Action] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            if "=" in line or line.startswith("["):
                raise TransitionTemplateError(
                    "template_parse_error",
                    "Equals/table-style transition files are unsupported; use the key: value transition sheet format",
                )
            raise TransitionTemplateError("template_parse_error", f"Line {line_number} is missing ':'")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise TransitionTemplateError("template_parse_error", f"Line {line_number} has an empty key")
        if key == "require":
            if not value:
                raise TransitionTemplateError("template_parse_error", f"Line {line_number} has an empty requirement")
            requirements.append(value)
        elif key == "anchor":
            name, expression = _parse_assignment(value, line_number=line_number, label="anchor")
            anchors[name] = expression
        elif key == "action":
            actions.append(_parse_action(value, line_number=line_number))
        else:
            fields[key] = _strip_optional_quotes(value)

    if "kind" not in fields:
        raise TransitionTemplateError("missing_field", "Missing required field: kind")
    return {"fields": fields, "requirements": requirements, "anchors": anchors, "actions": actions}


def _parse_assignment(value: str, *, line_number: int, label: str) -> tuple[str, str]:
    if "=" not in value:
        raise TransitionTemplateError("template_parse_error", f"Line {line_number} {label} must use name = expression")
    name, expression = value.split("=", 1)
    name = name.strip()
    expression = expression.strip()
    if not name or not expression:
        raise TransitionTemplateError("template_parse_error", f"Line {line_number} {label} has an empty side")
    return name, expression


def _parse_action(value: str, *, line_number: int) -> _Action:
    match = _ACTION_RE.match(value)
    if match is None:
        raise TransitionTemplateError(
            "template_parse_error",
            f"Line {line_number} action must look like: b.volume at 17.1 = 1 smooth",
        )
    return _Action(
        deck=match.group("deck").lower(),
        control=_control_name(match.group("control")),
        when=match.group("when").strip(),
        value=float(match.group("value")),
        interpolation=_interpolation(match.group("interpolation") or "straight"),
    )


def _drop_switch_context(
    fields: dict[str, str],
    *,
    bpm: float,
    beats_per_bar: int,
) -> tuple[dict[str, _DeckTiming], dict[str, Any], dict[str, dict[str, Any]]]:
    a_source_start = _field_time(fields, "song_a.play_from", bpm=bpm, beats_per_bar=beats_per_bar, default="1.1")
    b_source_start = _field_time(fields, "song_b.play_from", bpm=bpm, beats_per_bar=beats_per_bar)
    a_build = _field_time(fields, "song_a.build_start", bpm=bpm, beats_per_bar=beats_per_bar)
    a_drop = _field_time(fields, "song_a.drop_start", bpm=bpm, beats_per_bar=beats_per_bar)
    b_drop = _field_time(fields, "song_b.drop_start", bpm=bpm, beats_per_bar=beats_per_bar)
    a_cut = _field_time(
        fields,
        "song_a.cut_at",
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        default_seconds=max(a_build, a_drop - beats_per_bar * 60.0 / bpm),
    )
    b_build = _field_time(fields, "song_b.build_start", bpm=bpm, beats_per_bar=beats_per_bar, default_seconds=b_source_start)

    a_timeline_start = 0.0
    a_build_timeline = a_build - a_source_start + a_timeline_start
    a_drop_timeline = a_drop - a_source_start + a_timeline_start
    b_timeline_start = a_drop_timeline - (b_drop - b_source_start)
    transition_start = a_build_timeline
    transition_end = a_drop_timeline

    a_end = _field_time(
        fields,
        "song_a.end_at",
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        default_seconds=max(a_drop, a_cut),
    )
    b_end = _field_time(
        fields,
        "song_b.end_at",
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        default_seconds=b_drop + 16.0 * beats_per_bar * 60.0 / bpm,
    )
    timings = {
        "a": _deck_timing(
            "a",
            fields,
            source_start=a_source_start,
            source_end=a_end,
            timeline_start=a_timeline_start,
            timeline_end=max(a_cut - a_source_start, a_drop_timeline),
        ),
        "b": _deck_timing(
            "b",
            fields,
            source_start=b_source_start,
            source_end=b_end,
            timeline_start=b_timeline_start,
            timeline_end=b_timeline_start + max(0.0, b_end - b_source_start),
        ),
    }
    transition_id = _field(fields, "transition_id", _field(fields, "id", f"manual-drop-switch-{_timestamp_id()}"))
    family = _transition_family(fields)
    transition = {
        "transitionId": transition_id,
        "fromPlacementId": "place-a",
        "toPlacementId": "place-b",
        "technique": "build_to_drop_swap",
        "templateId": _field(fields, "template_id", "manual_drop_switch_barbeat_v1"),
        "timelineStartSeconds": _round(transition_start),
        "timelineEndSeconds": _round(transition_end),
        "handoffTimelineSeconds": _round(a_cut - a_source_start),
        "alignedDropTimelineSeconds": _round(a_drop_timeline),
        "measureCountToTarget": _round((a_drop - a_build) / (beats_per_bar * 60.0 / bpm)),
        "score": _number_field(fields, "score", 1.0),
        "reasons": [_field(fields, "notes", f"Manual {family} transition sheet")],
        "riskFlags": [],
    }
    source_anchors = _source_anchors(
        {
            "fromBuildStart": ("a", a_build),
            "fromDropStart": ("a", a_drop),
            "fromCutTime": ("a", a_cut),
            "toBuildStart": ("b", b_build),
            "toDropStart": ("b", b_drop),
            "a.buildStart": ("a", a_build),
            "a.dropStart": ("a", a_drop),
            "a.cutTime": ("a", a_cut),
            "b.playStart": ("b", b_source_start),
            "b.dropStart": ("b", b_drop),
        },
        timings,
    )
    return timings, transition, source_anchors


def _reverb_exit_context(
    fields: dict[str, str],
    *,
    bpm: float,
    beats_per_bar: int,
) -> tuple[dict[str, _DeckTiming], dict[str, Any], dict[str, dict[str, Any]]]:
    a_source_start = _field_time(fields, "song_a.play_from", bpm=bpm, beats_per_bar=beats_per_bar, default="1.1")
    b_source_start = _field_time(fields, "song_b.play_from", bpm=bpm, beats_per_bar=beats_per_bar, default="1.1")
    a_reverb_start = _field_time(fields, "song_a.reverb_start", bpm=bpm, beats_per_bar=beats_per_bar)
    a_drop_end = _field_time(fields, "song_a.drop_end", bpm=bpm, beats_per_bar=beats_per_bar)
    b_first_beat = _field_time(
        fields,
        "song_b.first_beat",
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        default_seconds=b_source_start,
    )
    tail_seconds = _number_field(fields, "tail_seconds", 14.0)
    a_drop_end_timeline = a_drop_end - a_source_start
    b_timeline_start = a_drop_end_timeline - (b_first_beat - b_source_start)
    transition_start = a_reverb_start - a_source_start
    transition_end = a_drop_end_timeline + tail_seconds

    a_end = _field_time(
        fields,
        "song_a.end_at",
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        default_seconds=a_drop_end + tail_seconds,
    )
    b_end = _field_time(
        fields,
        "song_b.end_at",
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        default_seconds=b_source_start + 16.0 * beats_per_bar * 60.0 / bpm,
    )
    timings = {
        "a": _deck_timing(
            "a",
            fields,
            source_start=a_source_start,
            source_end=a_end,
            timeline_start=0.0,
            timeline_end=transition_end,
        ),
        "b": _deck_timing(
            "b",
            fields,
            source_start=b_source_start,
            source_end=b_end,
            timeline_start=b_timeline_start,
            timeline_end=b_timeline_start + max(0.0, b_end - b_source_start),
        ),
    }
    transition = {
        "transitionId": _field(fields, "transition_id", _field(fields, "id", f"manual-reverb-exit-{_timestamp_id()}")),
        "fromPlacementId": "place-a",
        "toPlacementId": "place-b",
        "technique": "drop_end_reverb_exit",
        "templateId": _field(fields, "template_id", "manual_reverb_exit_barbeat_v1"),
        "timelineStartSeconds": _round(transition_start),
        "timelineEndSeconds": _round(transition_end),
        "handoffTimelineSeconds": _round(a_drop_end_timeline),
        "score": _number_field(fields, "score", 1.0),
        "reasons": [_field(fields, "notes", "Manual reverb-exit transition sheet")],
        "riskFlags": [],
    }
    source_anchors = _source_anchors(
        {
            "fromReverbStart": ("a", a_reverb_start),
            "fromDropEnd": ("a", a_drop_end),
            "toFirstBeat": ("b", b_first_beat),
            "a.reverbStart": ("a", a_reverb_start),
            "a.dropEnd": ("a", a_drop_end),
            "b.firstBeat": ("b", b_first_beat),
        },
        timings,
    )
    return timings, transition, source_anchors


def _automation_commands(
    actions: list[_Action],
    timings: dict[str, _DeckTiming],
    *,
    bpm: float,
    beats_per_bar: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for action in actions:
        timeline_seconds = _action_timeline_seconds(
            action.when,
            default_deck=action.deck,
            timings=timings,
            bpm=bpm,
            beats_per_bar=beats_per_bar,
        )
        grouped.setdefault((action.deck, action.control), []).append(
            {
                "at": _round(timeline_seconds),
                "value": _round(action.value),
                "interpolation": action.interpolation,
            }
        )

    commands: list[dict[str, Any]] = []
    for (deck_id, control), keyframes in grouped.items():
        keyframes.sort(key=lambda item: float(item["at"]))
        commands.append(
            {
                "type": "automate",
                "at": keyframes[0]["at"],
                "deck": 1 if deck_id == "a" else 2,
                "control": control,
                "keyframes": keyframes,
            }
        )
    return commands


def _action_timeline_seconds(
    when: str,
    *,
    default_deck: str,
    timings: dict[str, _DeckTiming],
    bpm: float,
    beats_per_bar: int,
) -> float:
    reference_deck = default_deck
    reference_time = when.strip()
    match = re.fullmatch(r"(?P<deck>[abAB]):(?P<time>.+)", reference_time)
    if match is not None:
        reference_deck = match.group("deck").lower()
        reference_time = match.group("time").strip()
    deck = timings[reference_deck]
    source_seconds = _parse_time(
        reference_time,
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        first_beat_seconds=deck.first_beat_seconds,
    )
    return deck.timeline_start_seconds + source_seconds - deck.source_start_seconds


def _deck_timing(
    deck_id: str,
    fields: dict[str, str],
    *,
    source_start: float,
    source_end: float,
    timeline_start: float,
    timeline_end: float,
) -> _DeckTiming:
    prefix = f"song_{deck_id}"
    return _DeckTiming(
        deck_id=deck_id,
        track_id=_required_field(fields, f"{prefix}.track_id"),
        source_uri=_field(fields, f"{prefix}.file", _field(fields, f"{prefix}.source_uri", "")),
        source_start_seconds=_round(source_start),
        source_end_seconds=_round(max(source_start, source_end)),
        timeline_start_seconds=_round(timeline_start),
        timeline_end_seconds=_round(max(timeline_start, timeline_end)),
        first_beat_seconds=_number_field(fields, f"{prefix}.first_beat_seconds", 0.0),
    )


def _asset(deck: _DeckTiming) -> dict[str, Any]:
    if not deck.source_uri:
        raise TransitionTemplateError("missing_field", f"Missing non-empty field: song_{deck.deck_id}.file")
    return {
        "trackId": deck.track_id,
        "sourceUri": deck.source_uri,
        "formatHint": _format_hint(deck.source_uri),
        "durationSeconds": _round(deck.source_end_seconds),
    }


def _placement(deck: _DeckTiming) -> dict[str, Any]:
    placement = {
        "placementId": f"place-{deck.deck_id}",
        "trackId": deck.track_id,
        "deck": 1 if deck.deck_id == "a" else 2,
        "sourceStartSeconds": deck.source_start_seconds,
        "sourceEndSeconds": deck.source_end_seconds,
        "timelineStartSeconds": deck.timeline_start_seconds,
        "timelineEndSeconds": deck.timeline_end_seconds,
        "role": "primary" if deck.deck_id == "a" else "incoming",
    }
    return placement


def _source_anchors(
    anchors: dict[str, tuple[str, float]],
    timings: dict[str, _DeckTiming],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, (deck_id, source_seconds) in anchors.items():
        deck = timings[deck_id]
        result[name] = {
            "trackId": deck.track_id,
            "sourceSeconds": _round(source_seconds),
            "timelineSeconds": _round(deck.timeline_start_seconds + source_seconds - deck.source_start_seconds),
        }
    return result


def _field_time(
    fields: dict[str, str],
    key: str,
    *,
    bpm: float,
    beats_per_bar: int,
    default: str | None = None,
    default_seconds: float | None = None,
) -> float:
    value = fields.get(key, default)
    first_beat_seconds = _number_field(fields, f"{key.split('.')[0]}.first_beat_seconds", 0.0)
    if value is None:
        if default_seconds is not None:
            return _round(default_seconds)
        raise TransitionTemplateError("missing_field", f"Missing required bar/beat field: {key}")
    return _parse_time(value, bpm=bpm, beats_per_bar=beats_per_bar, first_beat_seconds=first_beat_seconds)


def _parse_time(value: str, *, bpm: float, beats_per_bar: int, first_beat_seconds: float) -> float:
    text = value.strip()
    if text.startswith("+"):
        raise TransitionTemplateError("invalid_time", f"Relative times are only supported in generic recipes: {value}")
    match = re.fullmatch(r"(?P<bar>\d+)\.(?P<beat>\d+)(?:\.(?P<fraction>\d+))?", text)
    if match is None:
        raise TransitionTemplateError(
            "invalid_time",
            f"Expected bar.beat time like 89.1 or 89.1.5, got {value!r}",
        )
    bar = int(match.group("bar"))
    beat = int(match.group("beat"))
    fraction_text = match.group("fraction")
    fraction = float(f"0.{fraction_text}") if fraction_text else 0.0
    if bar < 1 or beat < 1 or beat > beats_per_bar:
        raise TransitionTemplateError(
            "invalid_time",
            f"Bar/beat must start at 1.1 and beat must be 1-{beats_per_bar}: {value}",
        )
    beat_index = (bar - 1) * beats_per_bar + (beat - 1) + fraction
    return _round(first_beat_seconds + beat_index * 60.0 / bpm)


def _fields(template: dict[str, Any]) -> dict[str, str]:
    fields = template.get("fields")
    if not isinstance(fields, dict):
        raise TransitionTemplateError("template_invalid", "Parsed transition sheet is missing fields")
    return fields


def _actions(template: dict[str, Any]) -> list[_Action]:
    actions = template.get("actions")
    if not isinstance(actions, list):
        raise TransitionTemplateError("template_invalid", "Parsed transition sheet is missing actions")
    if not actions:
        raise TransitionTemplateError("missing_actions", "Transition sheet requires at least one action line")
    return actions


def _transition_family(fields: dict[str, str]) -> str:
    return _field(fields, "type", _field(fields, "family", "custom"))


def _bpm(fields: dict[str, str]) -> float:
    bpm = _number_field(fields, "bpm", 0.0)
    if bpm <= 0.0:
        bpm = _number_field(fields, "song_a.bpm", _number_field(fields, "song_b.bpm", 0.0))
    if bpm <= 0.0:
        raise TransitionTemplateError("missing_field", "Missing positive BPM field: bpm")
    return bpm


def _beats_per_bar(fields: dict[str, str]) -> int:
    beats = _number_field(fields, "beats_per_bar", 4.0)
    if not float(beats).is_integer() or beats <= 0:
        raise TransitionTemplateError("invalid_number", "beats_per_bar must be a positive integer")
    return int(beats)


def _required_field(fields: dict[str, str], key: str) -> str:
    value = fields.get(key)
    if value is None or value == "":
        raise TransitionTemplateError("missing_field", f"Missing required field: {key}")
    return value


def _field(fields: dict[str, str], key: str, default: str) -> str:
    value = fields.get(key)
    return value if value is not None and value != "" else default


def _number_field(fields: dict[str, str], key: str, default: float) -> float:
    value = fields.get(key)
    if value is None or value == "":
        return float(default)
    try:
        number = float(value)
    except ValueError as exc:
        raise TransitionTemplateError("invalid_number", f"Field {key} must be numeric") from exc
    if not math.isfinite(number):
        raise TransitionTemplateError("invalid_number", f"Field {key} must be finite")
    return number


def _bool_field(fields: dict[str, str], key: str, *, default: bool) -> bool:
    value = fields.get(key)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1", "on"}:
        return True
    if normalized in {"false", "no", "0", "off"}:
        return False
    raise TransitionTemplateError("invalid_boolean", f"Field {key} must be true or false")


def _interpolation(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"instant", "cut", "hold"}:
        return "hold"
    if normalized in {"straight", "linear"}:
        return "linear"
    if normalized in {"smooth", "smoothstep"}:
        return "smoothstep"
    if normalized in {"curve", "exponential"}:
        return "exponential"
    raise TransitionTemplateError(
        "invalid_interpolation",
        "Interpolation must be instant, straight, smooth, or curve",
    )


def _control_name(value: str) -> str:
    normalized = value.strip()
    aliases = {
        "low": "eqLow",
        "lowEq": "eqLow",
        "eq_low": "eqLow",
        "reverb": "reverbWet",
        "reverb_wet": "reverbWet",
        "tail": "reverbTailGain",
        "reverb_tail": "reverbTailGain",
        "echo": "echoWet",
        "echo_wet": "echoWet",
    }
    return aliases.get(normalized, normalized)


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _format_hint(source_uri: str) -> str:
    parsed = urlparse(source_uri)
    suffix = Path(parsed.path or source_uri).suffix.lstrip(".").lower()
    if suffix in {"wav", "mp3", "flac", "aiff"}:
        return suffix
    if suffix == "aif":
        return "aiff"
    return "unknown"


def _round(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded


def _timestamp_id() -> str:
    return re.sub(r"[^0-9]", "", datetime.now(UTC).isoformat())[:14]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
