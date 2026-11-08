"""Snapshot-derived single-factor generation pipeline."""
from .config import QualityConfig
from .features import FeatureRegistry

__all__ = ["FeatureRegistry", "QualityConfig"]
