"""Run with: python -m simulation.run --decks 6 --hands 10000."""

import argparse
import json
import sys
import time
from dataclasses import asdict

from core.rules import RuleConfig
from simulation.simulator import simulate


def main() -> int:
    parser = argparse.ArgumentParser(description="Finite-shoe basic-strategy simulation (3:2, American peek)")
    parser.add_argument("--decks", type=int, default=6, choices=range(4, 9))
    parser.add_argument("--hands", type=int, default=10_000, help="Initial rounds, before splits")
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--h17", action="store_true", help="Dealer hits soft 17")
    parser.add_argument("--no-das", action="store_true", help="Disallow double after split")
    parser.add_argument("--surrender", action="store_true", help="Allow late surrender")
    parser.add_argument("--penetration", type=float, default=0.75)
    parser.add_argument("--json", action="store_true", help="Print machine-readable result")
    parser.add_argument("--validate", action="store_true", help="Check default 6-deck baseline; requires 1M+ rounds")
    args = parser.parse_args()
    try:
        rules = RuleConfig(args.decks, args.h17, not args.no_das, args.surrender, args.penetration)
        if args.hands < 1:
            raise ValueError("hands must be positive")
        if args.validate and (rules != RuleConfig() or args.hands < 1_000_000):
            raise ValueError("--validate requires default rules and at least 1000000 hands")
    except ValueError as error:
        parser.error(str(error))

    started = time.perf_counter()

    def progress(completed: int) -> None:
        print(f"{completed:,}/{args.hands:,} rounds ({time.perf_counter() - started:.1f}s)", file=sys.stderr, flush=True)

    result = simulate(rules, args.hands, args.seed, progress)
    elapsed = time.perf_counter() - started
    if args.json:
        print(json.dumps({**asdict(result), "baseline_check": result.baseline_check(), "elapsed_seconds": elapsed}, indent=2))
    else:
        print(f"Rules: {rules.strategy_key}; {rules.decks} decks; penetration {rules.penetration:.0%}")
        print("3:2 blackjack, dealer peek, split to 4 hands, no resplit aces, one card per split ace")
        print(f"Rounds: {result.rounds:,} | Player hands: {result.player_hands:,} | Shoes: {result.shoes:,} | Seed: {result.seed}")
        print(f"Player net: {result.total_profit:+,.1f} units | Total wagered: {result.total_wagered:,}")
        print(f"House edge per initial wager: {result.house_edge:.4%}")
        if result.confidence_interval_95 is not None:
            low, high = result.confidence_interval_95
            print(f"Approximate 95% CI (shoe clusters): [{low:.4%}, {high:.4%}]")
        else:
            print("95% CI unavailable: fewer than two shoes")
        print(f"Default-rule 0.4–0.6% baseline: {result.baseline_check()}")
        print(f"Elapsed: {elapsed:.2f}s")
    return 1 if args.validate and result.baseline_check() != "compatible" else 0


if __name__ == "__main__":
    raise SystemExit(main())
