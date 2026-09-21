import json
import os
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .evaluator import SingleFactorMetrics


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


class FactorStorage:
    def __init__(self, root: Path | str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.metadata = dict(metadata or {})
        self.accepted_path = self.root / "accepted_factors.jsonl"
        self.rejected_path = self.root / "rejected_candidates.jsonl"
        self.index_path = self.root / "expression_index.json"
        self.state_path = self.root / "run_state.json"

    def _load_index(self) -> Dict[str, int]:
        if not self.index_path.exists():
            return {}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _atomic_write_json(self, path: Path, value: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(value, ensure_ascii=False, indent=2, default=_json_default)
        last_error: PermissionError | None = None
        for attempt in range(10):
            temporary.write_text(payload, encoding="utf-8")
            try:
                os.replace(temporary, path)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(min(0.1 * (attempt + 1), 1.0))
        try:
            path.write_text(payload, encoding="utf-8")
            return
        except PermissionError:
            return
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def record(self, metrics: SingleFactorMetrics) -> bool:
        index = self._load_index()
        if metrics.expression in index:
            return False
        target = self.accepted_path if metrics.accepted else self.rejected_path
        payload = asdict(metrics)
        payload.update(self.metadata)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        index[metrics.expression] = 1 if metrics.accepted else 0
        self._atomic_write_json(self.index_path, index)
        return True

    @property
    def accepted_count(self) -> int:
        return sum(value == 1 for value in self._load_index().values())

    @property
    def expression_count(self) -> int:
        return len(self._load_index())

    def load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save_state(self, state: Dict[str, Any]) -> None:
        self._atomic_write_json(self.state_path, state)
