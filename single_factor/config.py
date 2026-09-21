from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class DataConfig:
    source_csv: Path
    processed_dir: Path
    fields: Tuple[str, ...]
    target_horizon: int = 20
    max_backtrack_days: int = 100
    max_future_days: int = 30
    train_start: Optional[str] = None
    train_end: Optional[str] = None
    valid_start: Optional[str] = None
    valid_end: Optional[str] = None
    test_start: Optional[str] = None
    test_end: Optional[str] = None


@dataclass(frozen=True)
class UniverseConfig:
    industry: Optional[str] = None
    industry_column: Optional[str] = None
    industry_mapping_file: Optional[Path] = None
    min_amount: Optional[float] = None
    exclude_suspended: bool = True
    min_listed_days: int = 0


@dataclass(frozen=True)
class QualityConfig:
    min_coverage: float = 0.8
    min_train_ic: Optional[float] = None
    min_valid_ic: Optional[float] = None
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


@dataclass(frozen=True)
class RunConfig:
    source_csv: Path
    processed_dir: Path
    fields: Tuple[str, ...]
    target_horizon: int = 20
    target_factor_count: int = 10
    max_attempts: int = 100
    output_dir: Path = field(default_factory=lambda: Path("out/single_factor"))
    seed: int = 0
    device: str = "cpu"
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)

    def __post_init__(self) -> None:
        if not self.fields:
            raise ValueError("fields must contain at least one feature")
        if self.target_horizon <= 0:
            raise ValueError("target_horizon must be positive")
        if self.target_factor_count < 1:
            raise ValueError("target_factor_count must be at least 1")
        if self.max_attempts < self.target_factor_count:
            raise ValueError("max_attempts must be at least target_factor_count")
        if self.universe.min_listed_days < 0:
            raise ValueError("min_listed_days cannot be negative")

    def validate(self) -> None:
        """Validate the configuration before touching a large dataset."""
        self.__post_init__()
