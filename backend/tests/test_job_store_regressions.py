import json
from pathlib import Path
import pytest
from repositories.job_store import atomic_write_json


def test_failed_replace_preserves_old_status_and_raises(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    path.write_text('{"status":"running"}')
    def denied(*args):
        raise PermissionError("busy")
    monkeypatch.setattr(Path, "replace", denied)
    monkeypatch.setattr("repositories.job_store.time.sleep", lambda _: None)
    with pytest.raises(PermissionError):
        atomic_write_json(path, {"status": "finished"})
    assert json.loads(path.read_text())["status"] == "running"
    assert list(tmp_path.iterdir()) == [path]
