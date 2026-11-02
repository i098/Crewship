import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SAMPLE = "tests/test_check_paths.py"


def collected(shard=None):
    env = {k: v for k, v in os.environ.items() if k != "CREWSHIP_TEST_SHARD"}
    if shard:
        env["CREWSHIP_TEST_SHARD"] = shard
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", SAMPLE],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    )
    return [line for line in result.stdout.splitlines() if "::" in line]


def test_shards_partition_the_suite_exactly():
    everything = collected()
    shards = [collected(f"{k}/3") for k in (1, 2, 3)]
    assert len(everything) >= 3
    assert sorted(sum(shards, [])) == sorted(everything)
    assert all(shards)
