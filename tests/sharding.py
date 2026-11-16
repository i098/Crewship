"""Split collected tests over CI shards so they finish together.

tests/shard_durations.json maps a test id to its measured seconds; refresh it with
scripts/refresh_shard_durations.py. Known tests go greedily (longest first) to the
lightest shard. A test missing from the file still runs: it takes the next shard in
round-robin order, so a new test is never skipped.
"""

import json
from pathlib import Path

DURATIONS = Path(__file__).with_name("shard_durations.json")


def load_durations():
    return json.loads(DURATIONS.read_text())


def assign(nodeids, durations, count):
    """Return the 0-based shard of each test id, in the order of `nodeids`."""
    shards = [None] * len(nodeids)
    loads = [0.0] * count
    known = sorted((i for i, n in enumerate(nodeids) if n in durations), key=lambda i: (-durations[nodeids[i]], nodeids[i]))
    for i in known:
        target = loads.index(min(loads))
        shards[i] = target
        loads[target] += durations[nodeids[i]]
    unknown = [i for i, shard in enumerate(shards) if shard is None]
    for turn, i in enumerate(unknown):
        shards[i] = turn % count
    return shards
