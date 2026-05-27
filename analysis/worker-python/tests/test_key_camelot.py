from __future__ import annotations

import pytest

from autodj_analysis import (
    CamelotKeyError,
    camelot_to_tonic_mode,
    classify_camelot_compatibility,
    key_artifact_from_camelot,
    parse_camelot,
)


def test_parse_camelot_normalizes_whitespace_case_and_leading_zero() -> None:
    key = parse_camelot(" 09a ")

    assert key.camelot == "9A"
    assert key.number == 9
    assert key.letter == "A"
    assert key.tonic == "E"
    assert key.mode == "minor"


def test_parse_camelot_rejects_invalid_values() -> None:
    with pytest.raises(CamelotKeyError) as exc_info:
        parse_camelot("13C")

    assert exc_info.value.code == "camelot_invalid"


def test_camelot_to_tonic_mode_maps_major_and_minor_keys() -> None:
    assert camelot_to_tonic_mode("4A") == ("F", "minor")
    assert camelot_to_tonic_mode("12B") == ("E", "major")


def test_key_artifact_from_camelot_uses_detector_backend_not_rekordbox_truth() -> None:
    artifact = key_artifact_from_camelot("10A", confidence=1.5, backend="unit-detector")

    assert artifact["tonic"] == "B"
    assert artifact["mode"] == "minor"
    assert artifact["camelot"] == "10A"
    assert artifact["confidence"] == 1.0
    assert artifact["candidates"][0]["backend"] == "unit-detector"


def test_classify_camelot_compatibility_cases() -> None:
    assert classify_camelot_compatibility("9A", "9A").classification == "perfect"
    assert classify_camelot_compatibility("9A", "9B").classification == "relative"
    assert classify_camelot_compatibility("9A", "10A").classification == "adjacent"
    assert classify_camelot_compatibility("12A", "1A").classification == "adjacent"
    assert classify_camelot_compatibility("9A", "12B").classification == "parallel"
    assert classify_camelot_compatibility("9A", "4B").classification == "clash"
    assert classify_camelot_compatibility(None, "4B").classification == "unknown"
