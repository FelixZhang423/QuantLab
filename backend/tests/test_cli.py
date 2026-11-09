import unittest

from cli.main import build_parser


class CLITests(unittest.TestCase):
    def test_platform_commands_are_registered(self):
        parser = build_parser()
        actions = next(action for action in parser._actions if action.dest == "command")
        choices = set(actions.choices)
        self.assertFalse({"prepare-master", "prepare", "update"} & choices)

        self.assertTrue(
            {
                "create-pool",
                "generate-factors",
                "backtest-factors",
                "compose-factors",
                "migrate-results",
                "run-platform-job",
            }.issubset(choices)
        )

    def test_compose_factors_exposes_marginal_contribution_options(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "compose-factors",
                "--pool",
                "pool_a",
                "--factor-run",
                "run_a",
                "--config",
                "config.yaml",
                "--target-horizon",
                "5",
                "--min-marginal-ic-improvement",
                "0.001",
                "--min-marginal-rank-ic-improvement",
                "0.0",
                "--min-marginal-icir-improvement",
                "-0.1",
                "--min-marginal-rank-icir-improvement",
                "-0.2",
            ]
        )

        self.assertEqual(args.target_horizon, 5)
        self.assertAlmostEqual(args.min_marginal_ic_improvement, 0.001)
        self.assertAlmostEqual(args.min_marginal_rank_ic_improvement, 0.0)
        self.assertAlmostEqual(args.min_marginal_icir_improvement, -0.1)
        self.assertAlmostEqual(args.min_marginal_rank_icir_improvement, -0.2)

    def test_compose_factors_exposes_factor_filters(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "compose-factors",
                "--pool",
                "pool_a",
                "--factor-run",
                "run_a",
                "--config",
                "config.yaml",
                "--factor-id",
                "f1",
                "--factor-id",
                "f2",
                "--z-clip",
                "3",
            ]
        )

        self.assertEqual(args.factor_id, ["f1", "f2"])
        self.assertAlmostEqual(args.z_clip, 3.0)
        self.assertFalse(hasattr(args, "weight_method"))


if __name__ == "__main__":
    unittest.main()
