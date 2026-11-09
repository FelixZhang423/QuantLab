import json
import hashlib
import tempfile
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
        self.candidate_path = self.root / "candidate_factors.jsonl"
        self.accepted_path = self.candidate_path
        self._ensure_unfrozen()
        self.rejected_path = self.root / "rejected_candidates.jsonl"
        self.index_path = self.root / "expression_index.json"
        self.state_path = self.root / "run_state.json"

    def _load_index(self) -> Dict[str, int]:
        if not self.index_path.exists():
            return {}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _ensure_unfrozen(self) -> None:
        run_path = self.root / "factor_run.json"
        finished = run_path.exists() and json.loads(run_path.read_text(encoding="utf-8")).get("generation_status") == "finished"
        if finished or (self.root / "confirmation_request.json").exists():
            raise ValueError("Candidate set is frozen for confirmation; start a new PPO run")

    def _atomic_write_json(self, path: Path, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False, indent=2, default=_json_default)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        try:
            for attempt in range(10):
                try:
                    os.replace(temporary, path)
                    return
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(min(0.1 * (attempt + 1), 1.0))
        finally:
            temporary.unlink(missing_ok=True)

    def record(self, metrics: SingleFactorMetrics) -> bool:
        self._ensure_unfrozen()
        index = self._load_index()
        if metrics.expression in index:
            return False
        target = self.accepted_path if metrics.accepted else self.rejected_path
        payload = asdict(metrics)
        payload.update(self.metadata)
        if metrics.accepted:
            sequence = sum(value == 1 for value in index.values()) + 1
            digest = hashlib.sha256(metrics.expression.encode("utf-8")).hexdigest()[:10]
            payload.update(factor_id=f"factor_{sequence:04d}_{digest}", status="candidate")
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        index[metrics.expression] = 1 if metrics.accepted else 0
        self._atomic_write_json(self.index_path, index)
        return True

    @property
    def candidate_count(self) -> int:
        return self.accepted_count

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
