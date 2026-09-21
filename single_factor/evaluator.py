from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import torch

from custom_bt.canonical_expression import serialize_alphagen_expression

from ._vendor.alphagen.data.expression import Expression
from ._vendor.alphagen.utils.correlation import batch_pearsonr, batch_spearmanr

from .config import QualityConfig
from .data import PanelData


@dataclass(frozen=True)
class SegmentMetrics:
    ic: float
    rank_ic: float
    icir: float
    coverage: float
    valid_days: int


@dataclass(frozen=True)
class SingleFactorMetrics:
    expression: str
    ic: float
    rank_ic: float
    icir: float
    coverage: float
    score: float
    accepted: bool
    reason: Optional[str]
    segments: Dict[str, SegmentMetrics]


class SingleFactorEvaluator:
    def __init__(
        self,
        train_panel: PanelData,
        target_horizon: int,
        quality: Optional[QualityConfig] = None,
        valid_panel: Optional[PanelData] = None,
        test_panel: Optional[PanelData] = None,
    ) -> None:
        self.train_panel = train_panel
        self.valid_panel = valid_panel
        self.test_panel = test_panel
        self.target_horizon = target_horizon
        self.quality = quality or QualityConfig()

    def _segment_metrics(self, expr: Expression, panel: PanelData) -> SegmentMetrics:
        values = expr.evaluate(panel).float()
        target = panel.target(self.target_horizon).float()
        valid = ~(values.isnan() | target.isnan())
        coverage = valid.float().mean().item()
        valid_days = valid.sum(dim=1) >= 2
        if not bool(valid_days.any()):
            return SegmentMetrics(
                ic=float("nan"),
                rank_ic=float("nan"),
                icir=float("nan"),
                coverage=coverage,
                valid_days=0,
            )

        ics = batch_pearsonr(values, target)[valid_days]
        rank_ics = batch_spearmanr(values, target)[valid_days]
        ics = ics[~ics.isnan()]
        rank_ics = rank_ics[~rank_ics.isnan()]
        if len(ics) == 0 or len(rank_ics) == 0:
            return SegmentMetrics(
                ic=float("nan"),
                rank_ic=float("nan"),
                icir=float("nan"),
                coverage=coverage,
                valid_days=0,
            )

        ic = ics.mean().item()
        rank_ic = rank_ics.mean().item()
        ic_std = ics.std(unbiased=False).item()
        icir = ic / max(ic_std, 1e-6)
        return SegmentMetrics(
            ic=ic,
            rank_ic=rank_ic,
            icir=icir,
            coverage=coverage,
            valid_days=int(valid_days.sum().item()),
        )

    def _score(self, metrics: SegmentMetrics) -> float:
        if any(np.isnan(value) for value in (metrics.ic, metrics.rank_ic, metrics.icir)):
            return 0.0
        weights = self.quality
        total = (
            weights.score_ic_weight
            + weights.score_rank_ic_weight
            + weights.score_icir_weight
        )
        return float(
            (
                weights.score_ic_weight * abs(metrics.ic)
                + weights.score_rank_ic_weight * abs(metrics.rank_ic)
                + weights.score_icir_weight * np.tanh(abs(metrics.icir))
            )
            / total
        )

    @staticmethod
    def _threshold_failed(value: float, threshold: Optional[float]) -> bool:
        return threshold is not None and (np.isnan(value) or abs(value) < threshold)

    def _accept(self, segments: Dict[str, SegmentMetrics]) -> Optional[str]:
        train = segments["train"]
        if train.coverage < self.quality.min_coverage:
            return f"train coverage below {self.quality.min_coverage:.3f}"
        if self._threshold_failed(train.ic, self.quality.min_train_ic):
            return f"train IC below {self.quality.min_train_ic:.3f}"
        if self._threshold_failed(train.icir, self.quality.min_icir):
            return f"train ICIR below {self.quality.min_icir:.3f}"

        for name, threshold in (("valid", self.quality.min_valid_ic), ("test", self.quality.min_test_ic)):
            if name not in segments:
                continue
            if segments[name].coverage < self.quality.min_coverage:
                return f"{name} coverage below {self.quality.min_coverage:.3f}"
            if self._threshold_failed(segments[name].ic, threshold):
                return f"{name} IC below {threshold:.3f}"
        return None

    def evaluate(self, expr: Expression) -> SingleFactorMetrics:
        expression = serialize_alphagen_expression(expr)
        panels = {"train": self.train_panel}
        if self.valid_panel is not None:
            panels["valid"] = self.valid_panel
        if self.test_panel is not None:
            panels["test"] = self.test_panel
        try:
            segments = {
                name: self._segment_metrics(expr, panel)
                for name, panel in panels.items()
            }
            train = segments["train"]
            reason = self._accept(segments)
            return SingleFactorMetrics(
                expression=expression,
                ic=train.ic,
                rank_ic=train.rank_ic,
                icir=train.icir,
                coverage=train.coverage,
                score=self._score(train),
                accepted=reason is None,
                reason=reason,
                segments=segments,
            )
        except Exception as exc:
            return SingleFactorMetrics(
                expression=expression,
                ic=float("nan"),
                rank_ic=float("nan"),
                icir=float("nan"),
                coverage=0.0,
                score=0.0,
                accepted=False,
                reason=f"evaluation error: {type(exc).__name__}: {exc}",
                segments={},
            )
