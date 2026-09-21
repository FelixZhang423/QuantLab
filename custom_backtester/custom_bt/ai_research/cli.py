from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from custom_bt.ai_research.runner import AIResearchRunner


def run_cmd(args: argparse.Namespace) -> None:
    runner = AIResearchRunner(
        config_path=args.config,
        project_root=args.project_root,
        env_path=args.env,
    )
    result = runner.run_research_session(
        args.intent,
        session_id=args.session_id,
        pool_id=args.pool,
        max_candidates=args.max_candidates,
        execute_tools=args.execute_tools,
        execute_long_jobs=args.execute_long_jobs,
    )
    output = {
        "session_dir": str(result["session_dir"]),
        "summary": result["summary"],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI quant research Agent powered by DeepSeek.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Create a model-backed AI research session.")
    run.add_argument("intent", help="Natural language research goal.")
    run.add_argument("--config", default="configs/ai_research_agent.yaml")
    run.add_argument("--project-root", default=".")
    run.add_argument("--env", default=".env.local")
    run.add_argument("--session-id", default=None)
    run.add_argument("--pool", default=None)
    run.add_argument("--max-candidates", type=int, default=None)
    run.add_argument(
        "--execute-tools",
        action="store_true",
        help="Execute the model-generated tool plan after local validation.",
    )
    run.add_argument(
        "--execute-long-jobs",
        action="store_true",
        help="Run created platform jobs synchronously. Without this flag, jobs are created but left queued.",
    )
    run.set_defaults(func=run_cmd)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.config = Path(args.config)
    args.project_root = Path(args.project_root)
    args.env = Path(args.env)
    args.func(args)


if __name__ == "__main__":
    main()
