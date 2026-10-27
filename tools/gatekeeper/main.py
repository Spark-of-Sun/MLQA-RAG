"""CLI entry point for gatekeeper runner.

Usage:
    uv run python -m tools.gatekeeper.main --stage <n> --profile <name>
"""

from __future__ import annotations

import argparse
import sys

from tools.gatekeeper.runner import GatekeeperRunner


def main() -> int:
    """Run gatekeeper checks CLI."""
    parser = argparse.ArgumentParser(description="Evaluate MLQA-RAG stage gates")
    parser.add_argument("--stage", type=int, default=0, help="Stage to evaluate (default: 0)")
    parser.add_argument("--profile", type=str, default="mvp-a", help="Profile (default: mvp-a)")
    parser.add_argument(
        "--advance",
        action="store_true",
        help="Advance STAGE file if all evaluated gates pass",
    )
    args = parser.parse_args()

    runner = GatekeeperRunner()
    print(f"=== Evaluating Gate Checks (STAGE={args.stage}, PROFILE={args.profile}) ===")

    try:
        results = runner.run_stage_gates(stage=args.stage, profile=args.profile)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"Error running gatekeeper: {e}", file=sys.stderr)
        return 1

    all_passed = True
    for r in results:
        status_marker = "✅ PASS" if r.passed else "❌ FAIL"
        print(f"[{status_marker}] {r.gate_id: <6} {r.name: <25} -> {r.details}")
        if not r.passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        if args.advance:
            stage_file = runner.repo_root / "STAGE"
            stage_file.write_text(f"{args.stage}\n", encoding="utf-8")
            print(f"STAGE successfully advanced to {args.stage}.")
        print(f"All evaluated gates for Stage {args.stage} ({args.profile}) PASSED.")
        return 0

    print(f"One or more gates for Stage {args.stage} ({args.profile}) FAILED.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
