from dataclasses import dataclass
from typing import Optional
import math


@dataclass(frozen=True)
class QualityConfig:
    min_coverage: float = 0.9
    min_train_ic: float = 0.05
    min_train_rank_ic: float = 0.03
    min_valid_ic: float = 0.03
    min_valid_rank_ic: float = 0.03
    min_valid_icir: float = 0.3
    min_test_ic: float = 0.03
    min_test_rank_ic: float = 0.03
    min_test_icir: float = 0.3
    min_test_coverage: float = 0.9
    min_icir: float = 0.5
    score_ic_weight: float = 0.5
    score_rank_ic_weight: float = 0.3
    score_icir_weight: float = 0.2

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_coverage <= 1.0:
            raise ValueError("min_coverage must be between 0 and 1")
        for name in ("min_train_ic", "min_train_rank_ic", "min_valid_ic", "min_valid_rank_ic", "min_test_ic", "min_test_rank_ic", "min_test_coverage"):
            value = getattr(self, name)
            if value is None or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        for name in ("min_icir", "min_valid_icir", "min_test_icir"):
            value = getattr(self, name)
            if value is None or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        weights = (
            self.score_ic_weight,
            self.score_rank_ic_weight,
            self.score_icir_weight,
        )
        if any(not math.isfinite(weight) or weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("score weights must be non-negative and not all zero")
