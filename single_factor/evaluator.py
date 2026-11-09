from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import torch

from custom_bt.canonical_expression import serialize_alphagen_expression

from ._vendor.alphagen.data.expression import Expression, Operator
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
    degenerate: Optional[str] = None


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
        valid = torch.isfinite(values) & torch.isfinite(target)
        coverage = int(valid.sum().item()) / valid.numel() if valid.numel() else 0.0
        valid_days = valid.sum(dim=1) >= 2
        inf_ratio = float(torch.isinf(values).float().mean().item())
        if inf_ratio > 0.05:
            return SegmentMetrics(ic=float("nan"), rank_ic=float("nan"), icir=float("nan"),
                                  coverage=coverage, valid_days=int(valid_days.sum().item()),
                                  degenerate=f"degenerate cross-section (inf_ratio={inf_ratio:.2f})")
        if not bool(valid_days.any()):
            return SegmentMetrics(
                ic=float("nan"),
                rank_ic=float("nan"),
                icir=float("nan"),
                coverage=coverage,
                valid_days=0,
            )

        # 横截面几乎不变或大面积 inf 的表达式没有可交易信号，先判负，避免 IC 噪声。
        mean = torch.nanmean(values, dim=1, keepdim=True)
        std = torch.sqrt(torch.nanmean((values - mean) ** 2, dim=1))
        zero_std_ratio = float((std[valid_days] == 0).float().mean().item())
        inf_ratio = float(torch.isinf(values).float().mean().item())
        if zero_std_ratio > 0.8 or inf_ratio > 0.05:
            return SegmentMetrics(
                ic=float("nan"),
                rank_ic=float("nan"),
                icir=float("nan"),
                coverage=coverage,
                valid_days=int(valid_days.sum().item()),
                degenerate=(
                    f"degenerate cross-section (zero_std_ratio={zero_std_ratio:.2f}, "
                    f"inf_ratio={inf_ratio:.2f})"
                ),
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
        if any(not np.isfinite(value) for value in (metrics.ic, metrics.rank_ic, metrics.icir)):
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

    def _segment_rejection(self, name: str, metrics: SegmentMetrics, train_ic: float,
                           min_coverage: float, thresholds: tuple[float, float, float],
                           align_sign: bool = True) -> Optional[str]:
        if metrics.degenerate:
            return f"{name}: {metrics.degenerate}"
        if not np.isfinite(metrics.coverage) or metrics.coverage < min_coverage:
            return f"{name} coverage below {min_coverage:.3f}"
        for field, threshold in zip(("ic", "rank_ic", "icir"), thresholds):
            value = getattr(metrics, field)
            if not np.isfinite(value) or abs(value) < threshold:
                return f"{name} {field} below {threshold:.3f}"
            if align_sign and np.sign(value) != np.sign(train_ic):
                return f"{name} {field} sign differs from train IC"
        return None

    def _accept(self, segments: Dict[str, SegmentMetrics]) -> Optional[str]:
        train = segments["train"]
        if train.degenerate:
            return f"train: {train.degenerate}"
        if not np.isfinite(train.ic) or train.ic == 0:
            return "train IC must be finite and nonzero"
        quality = self.quality
        reason = self._segment_rejection("train", train, train.ic, quality.min_coverage,
                                        (quality.min_train_ic, quality.min_train_rank_ic, quality.min_icir),
                                        align_sign=False)
        if reason:
            return reason
        if "valid" not in segments:
            return "valid segment is required for candidate admission"
        return self._segment_rejection("valid", segments["valid"], train.ic, quality.min_coverage,
                                       (quality.min_valid_ic, quality.min_valid_rank_ic, quality.min_valid_icir))

    def confirmation_rejection(self, train_ic: float, test: SegmentMetrics) -> Optional[str]:
        """Final frozen-candidate gate; never used by PPO reward or admission."""
        if not np.isfinite(train_ic) or train_ic == 0:
            return "train IC must be finite and nonzero"
        quality = self.quality
        return self._segment_rejection("test", test, train_ic, quality.min_test_coverage,
                                       (quality.min_test_ic, quality.min_test_rank_ic, quality.min_test_icir))

    def evaluate_holdout(self, expr: Expression) -> SegmentMetrics:
        """Evaluate a frozen expression on the test set; never used for admission or PPO reward."""
        if self.test_panel is None:
            raise ValueError("No test panel configured")
        return self._segment_metrics(expr, self.test_panel)

    def evaluate(self, expr: Expression) -> SingleFactorMetrics:
        expression = serialize_alphagen_expression(expr)
        # 裸字段/裸常数不构成因子：即使它和未来收益有相关性，也不能进入合格因子池。
        if not isinstance(expr, Operator):
            return SingleFactorMetrics(
                expression=expression,
                ic=float("nan"),
                rank_ic=float("nan"),
                icir=float("nan"),
                coverage=0.0,
                score=0.0,
                accepted=False,
                reason="expression has no operator (raw field or constant is not a factor)",
                segments={},
            )
        panels = {"train": self.train_panel}
        if self.valid_panel is not None:
            panels["valid"] = self.valid_panel
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
