import argparse
import json
from pathlib import Path
from typing import Any, Dict

from .config import QualityConfig
from .data import PanelData
from .evaluator import SingleFactorEvaluator
from .features import FeatureRegistry
from .preprocess import materialize_memmap, preprocess_csv
from .runner import run_with_ppo
from .universe import IndustryPoolFilter


def _load_config(path: Path) -> Dict[str, Any]:
    resolved = path.expanduser().resolve()
    # utf-8-sig also accepts normal UTF-8 and JSON files saved by Windows
    # PowerShell, which commonly adds a BOM.
    config = json.loads(resolved.read_text(encoding="utf-8-sig"))
    config["_config_dir"] = str(resolved.parent)
    return config


def _path(value: str | None, config: Dict[str, Any] | None = None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() and config is not None:
        path = Path(config["_config_dir"]) / path
    return path.resolve()


def _load_code_filter(config: Dict[str, Any]) -> list[str] | None:
    """Load an optional stock-code whitelist for early preprocessing."""
    codes = config.get("preprocess_codes")
    codes_file = _path(config.get("preprocess_codes_file"), config)
    if codes_file is not None:
        codes = [
            line.strip()
            for line in codes_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return None if codes is None else [str(code) for code in codes]


def command_preprocess(config: Dict[str, Any]) -> None:
    result = preprocess_csv(
        source_csv=_path(config["source_csv"], config),
        output_dir=_path(config["processed_dir"], config),
        fields=config["fields"],
        chunksize=int(config.get("chunksize", 200_000)),
        limit_rows=config.get("limit_rows"),
        overwrite=bool(config.get("overwrite", False)),
        point_in_time_fields=config.get("point_in_time_fields", ()),
        codes=_load_code_filter(config),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def command_inspect_pool(config: Dict[str, Any]) -> None:
    processed = _path(config["processed_dir"], config)
    metadata = json.loads((processed / "metadata.json").read_text(encoding="utf-8"))
    result: Dict[str, Any] = {"dataset": metadata}
    mapping_path = _path(config.get("industry_mapping_file"), config)
    if mapping_path is not None:
        import pandas as pd

        mapping = pd.read_csv(mapping_path)
        result["mapping_rows"] = len(mapping)
        result["industry"] = config.get("industry")
        if config.get("industry") is None:
            result["pool_codes"] = sorted(mapping["code"].astype(str).unique().tolist())
        else:
            result["pool_codes"] = sorted(
                mapping.loc[
                    mapping["industry"].astype(str) == str(config["industry"]),
                    "code",
                ].astype(str).unique().tolist()
            )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def command_materialize(config: Dict[str, Any]) -> None:
    codes = config.get("pool_codes")
    codes_file = _path(config.get("pool_codes_file"), config)
    if codes_file is not None:
        codes = [line.strip() for line in codes_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = materialize_memmap(
        processed_dir=_path(config["processed_dir"], config),
        output_dir=_path(config["cache_dir"], config),
        codes=codes,
        fields=config["fields"],
        start=config["cache_start"],
        end=config["cache_end"],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def command_materialize_splits(config: Dict[str, Any]) -> None:
    """Materialize train/valid/test caches from one runtime config."""
    splits = config.get("cache_splits")
    if not isinstance(splits, dict) or not splits:
        raise ValueError("cache_splits must be a non-empty object")

    codes = config.get("pool_codes")
    codes_file = _path(config.get("pool_codes_file"), config)
    if codes_file is not None:
        codes = [
            line.strip()
            for line in codes_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    results = {}
    for name, split in splits.items():
        if not isinstance(split, dict):
            raise ValueError(f"cache split '{name}' must be an object")
        results[name] = materialize_memmap(
            processed_dir=_path(config["processed_dir"], config),
            output_dir=_path(split["cache_dir"], config),
            codes=codes,
            fields=config["fields"],
            start=split["cache_start"],
            end=split["cache_end"],
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))


def command_run(config: Dict[str, Any]) -> None:
    cache_dir = _path(config["cache_dir"], config)
    manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
    horizon = int(config.get("target_horizon", 20))
    panel_kwargs = {
        "max_backtrack_days": int(config.get("max_backtrack_days", 100)),
        "max_future_days": int(config.get("max_future_days", horizon)),
    }
    train_panel = PanelData.from_memmap(cache_dir, **panel_kwargs)
    valid_dir = _path(config.get("valid_cache_dir"), config)
    test_dir = _path(config.get("test_cache_dir"), config)
    valid_panel = PanelData.from_memmap(valid_dir, **panel_kwargs) if valid_dir else None
    test_panel = PanelData.from_memmap(test_dir, **panel_kwargs) if test_dir else None

    quality = QualityConfig(**config.get("quality", {}))
    evaluator = SingleFactorEvaluator(
        train_panel=train_panel,
        valid_panel=valid_panel,
        test_panel=test_panel,
        target_horizon=horizon,
        quality=quality,
    )
    registry = FeatureRegistry(manifest["fields"])
    print(json.dumps({
        "dataset_signature": manifest["signature"],
        "n_days": manifest["n_days"],
        "n_stocks": manifest["n_stocks"],
        "n_features": len(registry.names()),
        "target_horizon": horizon,
        "output_dir": str(_path(config["output_dir"], config)),
    }, ensure_ascii=False, indent=2))
    runner = run_with_ppo(
        feature_names=registry.names(),
        evaluator=evaluator,
        output_dir=_path(config["output_dir"], config),
        target_count=int(config["target_factor_count"]),
        max_attempts=int(config["max_attempts"]),
        dataset_signature=manifest["signature"],
        total_timesteps_per_rollout=int(config.get("rollout_timesteps", 2048)),
        seed=int(config.get("seed", 0)),
        device=config.get("device", "cpu"),
    )
    print(json.dumps({
        "accepted_count": runner.accepted_count,
        "attempts": runner.attempts,
        "target_reached": runner.target_reached,
        "attempts_exhausted": runner.attempts_exhausted,
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Single-factor generation pipeline")
    parser.add_argument(
        "command",
        choices=("preprocess", "materialize", "materialize-splits", "inspect-pool", "run"),
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = _load_config(args.config)
    if args.command == "preprocess":
        command_preprocess(config)
    elif args.command == "materialize":
        command_materialize(config)
    elif args.command == "materialize-splits":
        command_materialize_splits(config)
    elif args.command == "inspect-pool":
        command_inspect_pool(config)
    else:
        command_run(config)


if __name__ == "__main__":
    main()
