"""
Wing Digital Twin Offline Test CLI Entry Point.
"""

import argparse

from scripts.analysis import OfflineRunner
from dtwin.core.fatigue import set_random_seed
from scripts.logger import get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Offline Fatigue Analysis")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible results")
    parser.add_argument("--sample-rate", type=int, default=10, help="Sample rate in Hz")
    args = parser.parse_args()

    if args.seed is not None:
        set_random_seed(args.seed)
        logger.info("Random seed set to %d", args.seed)

    runner = OfflineRunner(sample_rate=args.sample_rate)
    runner.run(args.duration, seed=args.seed)


if __name__ == "__main__":
    main()