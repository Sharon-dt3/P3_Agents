"""Daily run entry point.

The real, tested daily-digest job (p1.publishing.daily_job.run_daily_digest_job,
scheduled per channel by p1.publishing.scheduler.build_scheduler) is fully
implemented -- see tests/unit/test_daily_job.py, tests/unit/test_scheduler.py,
and GC6 in src/p1/eval/chn18_cases.py. This script is not yet wired to call
it as a standalone long-running process (see README.md's Quick start section);
every test, the eval harness, and CHN-24/27's real runs all call
run_daily_digest_job directly instead.
"""


def main() -> None:
    print(
        "[run] The daily-digest job itself is implemented and tested "
        "(p1.publishing.daily_job.run_daily_digest_job) -- this entry point "
        "just doesn't call it yet. See README.md's Quick start section."
    )


if __name__ == "__main__":
    main()
