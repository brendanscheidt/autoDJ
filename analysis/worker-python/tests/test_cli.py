import json

from autodj_analysis.cli import main


def test_cli_classify_prints_json(capsys) -> None:
    exit_code = main(["classify", "cli-track.wav"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["primaryGenre"] == "dubstep"


def test_cli_analyze_writes_artifact_and_prints_path(tmp_path, capsys) -> None:
    exit_code = main(["analyze", "cli-track.wav", "--out", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert (tmp_path / "analyzed-track.json").exists()
