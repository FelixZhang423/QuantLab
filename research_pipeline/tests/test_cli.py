import json
import subprocess
import sys

from research_pipeline.research_system.cli import validate_snapshot


def test_validate_snapshot_reports_invalid_manifest(tmp_path):
    data_root = tmp_path / "research_data"
    snapshot = data_root / "snapshots" / "bad"
    snapshot.mkdir(parents=True)
    (data_root / "current.txt").write_text("bad\n", encoding="utf-8")
    (snapshot / "manifest.json").write_text(
        json.dumps({"snapshot_id": "bad", "valid": True, "files": []}),
        encoding="utf-8",
    )

    result = validate_snapshot(data_root)

    assert result["valid"] is False
    assert result["errors"]


def test_module_help_exposes_export_and_validate():
    completed = subprocess.run(
        [sys.executable, "-m", "research_pipeline.research_system", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "export" in completed.stdout
    assert "validate" in completed.stdout
    assert "states" in completed.stdout
    assert "values" in completed.stdout
    assert "conditional" in completed.stdout
    assert "select" in completed.stdout


def test_select_cli_parses_training_selection_options():
    from research_pipeline.research_system.cli import build_parser

    args = build_parser().parse_args([
        "select",
        "--conditional-run", "conditional",
        "--state-id", "bull",
        "--split", "valid",
        "--top-n", "5",
    ])

    assert args.state_id == "bull"
    assert args.split == "valid"
    assert args.top_n == 5
