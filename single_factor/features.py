from typing import Iterable, Sequence, Tuple


_FORBIDDEN_NAMES = {
    "code",
    "category",
    "timestamps",
    "date",
    "industry",
    "name",
    "chiname",
    "engname",
    "infopubldate",
    "enddate",
}


class FeatureRegistry:
    """Ordered, validated mapping from expression names to panel columns."""

    def __init__(self, names: Sequence[str]):
        normalized = tuple(str(name).strip() for name in names)
        if not normalized or any(not name for name in normalized):
            raise ValueError("feature names must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("feature names must be unique")
        forbidden = [name for name in normalized if name.lower() in _FORBIDDEN_NAMES]
        if forbidden:
            raise ValueError(f"forbidden feature names: {forbidden}")
        self._names: Tuple[str, ...] = normalized
        self._indices = {name: index for index, name in enumerate(normalized)}

    def index(self, name: str) -> int:
        return self._indices[name]

    def names(self) -> Tuple[str, ...]:
        return self._names

    def validate(self, available_columns: Iterable[str]) -> None:
        available = set(available_columns)
        missing = [name for name in self._names if name not in available]
        if missing:
            raise ValueError(f"missing feature columns: {missing}")
