from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodj_analysis import TransitionTemplateError, parse_transition_template_file


def test_parse_specific_drop_switch_transition_sheet_writes_mix_plan(tmp_path: Path) -> None:
    template_path = tmp_path / "drop-switch.transition.txt"
    template_path.write_text(
        """
# First beat in each analyzed beatgrid is bar 1.1.
kind: specific_transition
type: drop_switch
plan_id: manual-plan-test
transition_id: transition-test
bpm: 145
notes: Manual drop switch from Rekordbox bar stamps

song_a.track_id: strangers
song_a.file: C:/Music/strangers.mp3
song_a.play_from: 1.1
song_a.build_start: 89.1
song_a.drop_start: 105.1
song_a.cut_at: 104.1
song_a.end_at: 105.1

song_b.track_id: lets-go-back
song_b.file: C:/Music/lets-go-back.mp3
song_b.play_from: 17.1
song_b.drop_start: 33.1
song_b.end_at: 49.1

action: b.volume at 17.1 = 0 instant
action: b.volume at 25.1 = 1 smooth
action: a.volume at 104.1 = 0 instant
""",
        encoding="utf-8",
    )

    result = parse_transition_template_file(template_path, tmp_path / "mix-plan.json")

    payload = json.loads(result.output_path.read_text(encoding="utf-8"))
    assert result.artifact == "mix-plan"
    assert payload["planId"] == "manual-plan-test"
    transition = payload["transitions"][0]
    assert transition["technique"] == "build_to_drop_swap"
    assert transition["measureCountToTarget"] == 16.0
    assert transition["sourceAnchors"]["fromBuildStart"]["sourceSeconds"] == pytest.approx(145.655172)
    assert transition["sourceAnchors"]["toBuildStart"]["sourceSeconds"] == pytest.approx(26.482759)
    assert transition["sourceAnchors"]["fromDropStart"]["timelineSeconds"] == pytest.approx(
        transition["sourceAnchors"]["toDropStart"]["timelineSeconds"]
    )
    assert payload["commands"][0]["type"] == "load"
    volume_b = next(command for command in payload["commands"] if command.get("deck") == 2 and command.get("control") == "volume")
    assert volume_b["keyframes"][0]["at"] == pytest.approx(145.655172)
    assert volume_b["keyframes"][1]["at"] == pytest.approx(158.896552)
    assert volume_b["keyframes"][1]["interpolation"] == "smoothstep"


def test_parse_generic_transition_sheet_writes_recipe(tmp_path: Path) -> None:
    template_path = tmp_path / "generic.recipe.txt"
    template_path.write_text(
        """
kind: generic_transition
type: drop_switch
recipe_id: drop-switch-energy-managed
notes: Use when both songs have exact BPM and compatible build energy
energy_notes: Incoming drop should not feel weaker than layered build
require: same_bpm
require: song_a.second_build
require: song_a.second_drop
require: song_b.first_drop
anchor: a_start = song_a.second_build.start
anchor: a_drop = song_a.second_drop.start
anchor: a_cut = a_drop - 1 bar
anchor: b_drop = song_b.first_drop.start
anchor: b_start = b_drop - distance(a_start, a_drop)
action: b.volume at b_start = 0 instant
action: b.volume at midpoint(b_start, b_drop) = 1 smooth
""",
        encoding="utf-8",
    )

    result = parse_transition_template_file(template_path, tmp_path / "recipe.json")

    payload = json.loads(result.output_path.read_text(encoding="utf-8"))
    assert result.artifact == "transition-recipe"
    assert payload["recipeId"] == "drop-switch-energy-managed"
    assert payload["transitionFamily"] == "drop_switch"
    assert payload["semanticRequirements"]["exactBpmRequired"] is True
    assert payload["semanticRequirements"]["anchors"]["b_start"] == "b_drop - distance(a_start, a_drop)"
    assert payload["automation"]["b"]["volume"][1]["timeExpression"] == "midpoint(b_start, b_drop)"


def test_parse_specific_double_drop_sheet_accepts_friendly_reverb_alias(tmp_path: Path) -> None:
    template_path = tmp_path / "double-drop.transition.txt"
    template_path.write_text(
        """
kind: specific_transition
type: double_drop
plan_id: double-drop-test
transition_id: double-drop
bpm: 140
song_a.track_id: as-i-do
song_a.file: C:/Music/as-i-do.mp3
song_a.play_from: 1.1
song_a.build_start: 45.1
song_a.drop_start: 61.1
song_a.cut_at: 85.1
song_a.end_at: 85.1
song_b.track_id: shock-therapy
song_b.file: "C:/Music/shock-therapy.mp3"
song_b.play_from: 1.1
song_b.drop_start: 17.1
song_b.end_at: 49.1
action: a.reverb at 77.1 = 1 smooth
action: b.volume at 1.1 = 0 instant
""",
        encoding="utf-8",
    )

    result = parse_transition_template_file(template_path, tmp_path / "mix-plan.json")

    payload = json.loads(result.output_path.read_text(encoding="utf-8"))
    assert result.artifact == "mix-plan"
    assert payload["transitions"][0]["technique"] == "double_drop"
    assert payload["assets"][1]["sourceUri"] == "C:/Music/shock-therapy.mp3"
    reverb_command = next(command for command in payload["commands"] if command.get("control") == "reverbWet")
    assert reverb_command["deck"] == 1


def test_equals_style_transition_files_are_not_supported(tmp_path: Path) -> None:
    template_path = tmp_path / "old-style.transition.txt"
    template_path.write_text('kind = "specific_transition"\n', encoding="utf-8")

    with pytest.raises(TransitionTemplateError) as exc_info:
        parse_transition_template_file(template_path, tmp_path / "out.json")

    assert exc_info.value.code == "template_parse_error"
