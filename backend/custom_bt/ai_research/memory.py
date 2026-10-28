from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


class ExperimentStore:
    """Filesystem-backed store for AI research sessions and long-term memory."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.sessions_root = self.root / "sessions"
        self.memory_root = self.root / "memory"

    def create_session(self, session_id: str, research_spec: Mapping[str, Any]) -> Path:
        session_id = self._safe_stem(session_id, "session_id")
        if not session_id:
            raise ValueError("session_id is required")
        session_dir = self.sessions_root / session_id
        session_dir.mkdir(parents=True, exist_ok=False)
        self.write_json(session_dir / "research_spec.json", dict(research_spec))
        return session_dir

    def write_json(self, path: str | Path, payload: Mapping[str, Any]) -> Path:
        output_path = self._resolve_under_root(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return output_path

    def append_jsonl(self, path: str | Path, payload: Mapping[str, Any]) -> Path:
        output_path = self._resolve_under_root(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(payload)
        if "created_at" not in row:
            row["created_at"] = datetime.now().isoformat(timespec="seconds")
        with output_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return output_path

    def memory_path(self, memory_name: str) -> Path:
        safe_name = self._safe_stem(memory_name, "memory_name")
        if safe_name.endswith(".jsonl"):
            safe_name = safe_name[:-6]
        return self.memory_root / f"{safe_name}.jsonl"

    def append_memory(self, memory_name: str, payload: Mapping[str, Any]) -> Path:
        return self.append_jsonl(self.memory_path(memory_name), payload)

    def _resolve_under_root(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved_root = self.root.resolve()
        resolved_candidate = candidate.resolve()
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"path must stay under research root: {resolved_root}") from exc
        return resolved_candidate

    @staticmethod
    def _safe_stem(value: str, label: str) -> str:
        item = str(value).strip()
        if not item:
            raise ValueError(f"{label} is required")
        path = Path(item)
        if path.is_absolute() or len(path.parts) != 1 or item in {".", ".."}:
            raise ValueError(f"{label} must be a simple file stem")
        if "/" in item or "\\" in item:
            raise ValueError(f"{label} must be a simple file stem")
        return item
