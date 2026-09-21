from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .evaluator import SingleFactorMetrics
from .storage import FactorStorage


class FactorRunner:
    def __init__(
        self,
        target_count: int,
        max_attempts: int,
        storage: FactorStorage,
        dataset_signature: Optional[str] = None,
    ) -> None:
        if target_count < 1:
            raise ValueError("target_count must be positive")
        if max_attempts < target_count:
            raise ValueError("max_attempts must be at least target_count")
        self.target_count = target_count
        self.max_attempts = max_attempts
        self.storage = storage
        state = storage.load_state()
        previous_signature = state.get("dataset_signature")
        if (
            previous_signature is not None
            and dataset_signature is not None
            and previous_signature != dataset_signature
        ):
            raise ValueError("processed dataset signature does not match run state")
        self.attempts = int(state.get("attempts", 0))
        self.accepted_count = storage.accepted_count
        self.dataset_signature = dataset_signature or previous_signature
        self._save_state()

    @property
    def target_reached(self) -> bool:
        return self.accepted_count >= self.target_count

    @property
    def attempts_exhausted(self) -> bool:
        return self.attempts >= self.max_attempts

    def can_continue(self) -> bool:
        return not self.target_reached and not self.attempts_exhausted

    def _save_state(self) -> None:
        self.storage.save_state({
            "attempts": self.attempts,
            "accepted_count": self.accepted_count,
            "target_count": self.target_count,
            "max_attempts": self.max_attempts,
            "dataset_signature": self.dataset_signature,
        })

    def register_attempt(self) -> None:
        if not self.can_continue():
            return
        self.attempts += 1
        self._save_state()

    def record(self, metrics: SingleFactorMetrics) -> bool:
        added = self.storage.record(metrics)
        if added and metrics.accepted:
            self.accepted_count += 1
            self._save_state()
            return True
        return False

    def set_checkpoint(self, checkpoint: str) -> None:
        state = self.storage.load_state()
        state["latest_checkpoint"] = checkpoint
        self.storage.save_state(state)


def run_with_ppo(
    feature_names: Sequence[str],
    evaluator,
    output_dir: Path | str,
    target_count: int,
    max_attempts: int,
    dataset_signature: Optional[str] = None,
    total_timesteps_per_rollout: int = 2048,
    seed: int = 0,
    device: str = "cpu",
    storage_metadata: Optional[Dict[str, Any]] = None,
) -> FactorRunner:
    """Run masked PPO until enough qualified single factors are stored."""
    try:
        from sb3_contrib.ppo_mask import MaskablePPO
        from stable_baselines3.common.callbacks import BaseCallback
    except ImportError as exc:
        raise RuntimeError(
            "PPO execution requires stable-baselines3, sb3-contrib, and gymnasium"
        ) from exc

    from ._vendor.alphagen.rl.policy import LSTMSharedNet

    from .environment import SingleFactorEnv

    storage = FactorStorage(output_dir, metadata=storage_metadata)
    runner = FactorRunner(
        target_count=target_count,
        max_attempts=max_attempts,
        storage=storage,
        dataset_signature=dataset_signature,
    )
    env = SingleFactorEnv(feature_names=feature_names, evaluator=evaluator)
    checkpoint_dir = Path(output_dir) / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    class FactorCallback(BaseCallback):
        def _on_step(self) -> bool:
            return True

        def _on_rollout_end(self) -> None:
            for wrapped_env in self.training_env.envs:
                core = wrapped_env.unwrapped
                for metrics in core.drain_completed_metrics():
                    runner.register_attempt()
                    runner.record(metrics)
            if not runner.can_continue():
                self.continue_training = False

    state = storage.load_state()
    latest_checkpoint = state.get("latest_checkpoint")
    if latest_checkpoint and Path(latest_checkpoint).exists():
        model = MaskablePPO.load(latest_checkpoint, env=env, device=device)
    else:
        model = MaskablePPO(
            "MlpPolicy",
            env,
            policy_kwargs={
                "features_extractor_class": LSTMSharedNet,
                "features_extractor_kwargs": {
                    "n_layers": 2,
                    "d_model": 128,
                    "dropout": 0.1,
                    "device": device,
                },
            },
            n_steps=total_timesteps_per_rollout,
            batch_size=min(128, total_timesteps_per_rollout),
            gamma=1.0,
            ent_coef=0.01,
            seed=seed,
            device=device,
            verbose=0,
        )

    while runner.can_continue():
        model.learn(
            total_timesteps=total_timesteps_per_rollout,
            callback=FactorCallback(verbose=0),
            reset_num_timesteps=False,
        )
        checkpoint = checkpoint_dir / f"{model.num_timesteps}_steps"
        model.save(checkpoint)
        runner.set_checkpoint(str(checkpoint))
        if runner.attempts_exhausted or runner.target_reached:
            break
    return runner
