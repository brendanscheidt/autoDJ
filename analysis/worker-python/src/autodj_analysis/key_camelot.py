"""Camelot key parsing, mapping, and compatibility utilities."""

from __future__ import annotations

from dataclasses import dataclass
import re


class CamelotKeyError(ValueError):
    """Expected Camelot parsing failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class CamelotKey:
    number: int
    letter: str
    camelot: str
    tonic: str
    mode: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "number": self.number,
            "letter": self.letter,
            "camelot": self.camelot,
            "tonic": self.tonic,
            "mode": self.mode,
        }


@dataclass(frozen=True)
class KeyCompatibility:
    classification: str
    score: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "score": self.score,
            "reasons": list(self.reasons),
        }


_CAMELOT_PATTERN = re.compile(r"^\s*(?P<number>0?[1-9]|1[0-2])\s*(?P<letter>[abAB])\s*$")

_CAMELOT_TO_TONIC_MODE: dict[str, tuple[str, str]] = {
    "1A": ("A-flat", "minor"),
    "2A": ("E-flat", "minor"),
    "3A": ("B-flat", "minor"),
    "4A": ("F", "minor"),
    "5A": ("C", "minor"),
    "6A": ("G", "minor"),
    "7A": ("D", "minor"),
    "8A": ("A", "minor"),
    "9A": ("E", "minor"),
    "10A": ("B", "minor"),
    "11A": ("F-sharp", "minor"),
    "12A": ("D-flat", "minor"),
    "1B": ("B", "major"),
    "2B": ("F-sharp", "major"),
    "3B": ("D-flat", "major"),
    "4B": ("A-flat", "major"),
    "5B": ("E-flat", "major"),
    "6B": ("B-flat", "major"),
    "7B": ("F", "major"),
    "8B": ("C", "major"),
    "9B": ("G", "major"),
    "10B": ("D", "major"),
    "11B": ("A", "major"),
    "12B": ("E", "major"),
}
_TONIC_MODE_TO_CAMELOT = {value: key for key, value in _CAMELOT_TO_TONIC_MODE.items()}


def parse_camelot(value: str | None) -> CamelotKey:
    """Parse a Camelot key such as ``9A`` or `` 09a ``."""

    if value is None or not str(value).strip():
        raise CamelotKeyError("camelot_missing", "Camelot key value is missing")
    match = _CAMELOT_PATTERN.match(str(value))
    if match is None:
        raise CamelotKeyError("camelot_invalid", f"Camelot key value is invalid: {value!r}")

    number = int(match.group("number"))
    letter = match.group("letter").upper()
    camelot = f"{number}{letter}"
    tonic, mode = _CAMELOT_TO_TONIC_MODE[camelot]
    return CamelotKey(number=number, letter=letter, camelot=camelot, tonic=tonic, mode=mode)


def camelot_to_tonic_mode(value: str) -> tuple[str, str]:
    """Return conventional tonic/mode names for a Camelot key."""

    key = parse_camelot(value)
    return key.tonic, key.mode


def camelot_from_tonic_mode(tonic: str, mode: str) -> str:
    """Return Camelot notation for canonical tonic/mode names."""

    normalized = (_normalize_tonic(tonic), mode.strip().lower())
    try:
        return _TONIC_MODE_TO_CAMELOT[normalized]
    except KeyError:
        raise CamelotKeyError(
            "tonic_mode_unmapped",
            f"Tonic/mode pair cannot be mapped to Camelot: {tonic!r} {mode!r}",
        ) from None


def key_artifact_from_camelot(
    value: str,
    *,
    confidence: float,
    backend: str,
) -> dict[str, object]:
    """Build the analyzed-track key shape from a detector Camelot result."""

    key = parse_camelot(value)
    bounded_confidence = max(0.0, min(1.0, float(confidence)))
    return {
        "tonic": key.tonic,
        "mode": key.mode,
        "camelot": key.camelot,
        "confidence": bounded_confidence,
        "candidates": [
            {
                "tonic": key.tonic,
                "mode": key.mode,
                "camelot": key.camelot,
                "confidence": bounded_confidence,
                "backend": backend,
            }
        ],
    }


def classify_camelot_compatibility(
    source: str | None,
    target: str | None,
) -> KeyCompatibility:
    """Classify DJ usefulness between two Camelot keys."""

    if source is None or target is None or not str(source).strip() or not str(target).strip():
        return KeyCompatibility("unknown", 0.4, ("missing_key",))

    try:
        first = parse_camelot(source)
        second = parse_camelot(target)
    except CamelotKeyError as exc:
        return KeyCompatibility("unknown", 0.4, (exc.code,))

    if first.camelot == second.camelot:
        return KeyCompatibility("perfect", 1.0, ("same_camelot_key",))

    if first.number == second.number and first.letter != second.letter:
        return KeyCompatibility("relative", 0.9, ("same_number_opposite_mode",))

    if first.letter == second.letter and _numbers_are_adjacent(first.number, second.number):
        return KeyCompatibility("adjacent", 0.8, ("neighboring_camelot_number_same_mode",))

    if first.tonic == second.tonic and first.mode != second.mode:
        return KeyCompatibility("parallel", 0.55, ("same_tonic_opposite_mode",))

    return KeyCompatibility("clash", 0.0, ("distant_camelot_key",))


def _numbers_are_adjacent(first: int, second: int) -> bool:
    return (first % 12) + 1 == second or (second % 12) + 1 == first


def _normalize_tonic(value: str) -> str:
    cleaned = value.strip()
    aliases = {
        "Ab": "A-flat",
        "A#": "B-flat",
        "Bb": "B-flat",
        "C#": "D-flat",
        "Db": "D-flat",
        "D#": "E-flat",
        "Eb": "E-flat",
        "F#": "F-sharp",
        "Gb": "F-sharp",
        "G#": "A-flat",
    }
    return aliases.get(cleaned, cleaned)
