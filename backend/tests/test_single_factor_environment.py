import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from single_factor._vendor.alphagen.data.expression import Abs, Add, Corr, Div, Mean
from single_factor.environment import SingleFactorEnv


class _StubMetrics:
    expression = "$close"
    score = 0.0


class _StubEvaluator:
    def evaluate(self, expression):
        return _StubMetrics()


class SingleFactorEnvironmentMaskTests(unittest.TestCase):
    def _env(self, operators):
        return SingleFactorEnv(
            ["close", "amount"],
            evaluator=_StubEvaluator(),
            operators=operators,
        )

    @staticmethod
    def _delta_time_index(env):
        return env.size_op + env.size_feature + env.size_constant

    def test_delta_time_disabled_when_subset_has_no_rolling_operator(self):
        # add/div 都是二元算子，无法消费 DeltaTime；如果不屏蔽 1d，
        # 加进去后动作掩码会全 False，MaskablePPO 会随机采样出非法 token。
        env = self._env([Add, Div])
        env.reset()
        env.step(env.size_op)  # 第一个 feature：$close

        dt_index = self._delta_time_index(env)
        mask = env.action_masks()
        self.assertFalse(mask[dt_index:dt_index + env.size_delta_time].any())
        self.assertTrue(mask.any())

    def test_pair_rolling_delta_time_needs_two_featured_operands(self):
        env = self._env([Corr])
        env.reset()
        env.step(env.size_op)  # 1 个 feature 不够 ts_corr
        dt_index = self._delta_time_index(env)
        self.assertFalse(env.action_masks()[dt_index])

        env.step(env.size_op)  # 2 个 feature 才允许 DeltaTime
        mask = env.action_masks()
        self.assertTrue(mask[dt_index])

        env.step(dt_index)
        mask = env.action_masks()
        self.assertTrue(mask[0])  # 唯一的 Corr 可以收尾
        self.assertEqual(int(mask.sum()), 1)

    def test_rolling_operator_keeps_delta_time_enabled(self):
        env = self._env([Mean])
        env.reset()
        env.step(env.size_op)
        dt_index = self._delta_time_index(env)
        self.assertTrue(env.action_masks()[dt_index])

        env.step(dt_index)
        mask = env.action_masks()
        self.assertTrue(mask[0])
        self.assertEqual(int(mask.sum()), 1)

    def test_raw_feature_cannot_terminate_without_operator(self):
        env = self._env([Abs])
        env.reset()
        sep_index = env.size_action - 1

        env.step(env.size_op)  # 只选了一个 feature：$close
        self.assertFalse(env.action_masks()[sep_index])

        env.step(0)  # 套上 Abs，表达式才完整
        self.assertTrue(env.action_masks()[sep_index])

        _, reward, done, _, _ = env.step(sep_index)
        self.assertTrue(done)
        self.assertEqual(reward, 0.0)

    def test_random_masked_actions_never_dead_end(self):
        rng = random.Random(7)
        subsets = [
            [Add, Div],
            [Mean],
            [Corr],
            [Add, Div, Mean, Corr],
        ]
        for operators in subsets:
            env = self._env(operators)
            env.reset()
            for _ in range(2000):
                mask = env.action_masks()
                valid_actions = mask.nonzero()[0]
                self.assertGreater(len(valid_actions), 0)

                _, _, done, _, _ = env.step(int(rng.choice(valid_actions)))
                if done:
                    env.reset()


if __name__ == "__main__":
    unittest.main()
