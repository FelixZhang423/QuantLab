from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class QualityConfig:
    min_coverage: float = 0.8
    min_train_ic: Optional[float] = None
    min_valid_ic: Optional[float] = None
    # Legacy config compatibility only; test data never gates candidate admission.
    min_test_ic: Optional[float] = None
    min_icir: Optional[float] = None
    score_ic_weight: float = 0.5
    score_rank_ic_weight: float = 0.3
    score_icir_weight: float = 0.2

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_coverage <= 1.0:
            raise ValueError("min_coverage must be between 0 and 1")
        weights = (
            self.score_ic_weight,
            self.score_rank_ic_weight,
            self.score_icir_weight,
        )
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("score weights must be non-negative and not all zero")
