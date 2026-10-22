import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


@pytest.mark.parametrize("environment,model,effort,expected", [
    ({}, "claude-opus-5-5", "xhigh", "high"),
    ({}, "claude-opus-5-5", "max", "high"),
    ({}, "claude-opus-5-5", "high", "high"),
    ({}, "claude-opus-5-5", "medium", "medium"),
    ({}, "claude-opus-5-5", "low", "low"),
    ({}, "claude-opus-5-5", None, None),
    ({}, "claude-opus-5-5", "toString", "toString"),
    ({}, "claude-sonnet-5-5", "max", "max"),
    ({"OMP_SKIP_SETUP": ""}, "claude-opus-5-5", "max", "max"),
    ({"FM_OMP_HARNESS": ""}, "claude-opus-5-5", "max", "max"),
    ({"FM_OPUS_EFFORT_UNCAPPED": "1"}, "claude-opus-5-5", "max", "max"),
])
def test_provider_effort_cap(environment, model, effort, expected):
    extension = json.dumps(str(ROOT / "blueprint/config/omp-opus-effort-cap.ts"))
    payload = {"model": model, "messages": [], "output_config": {"effort": effort, "format": "json"}}
    code = f"""
import extension from {extension};
let handler;
extension({{ on: (_event, callback) => {{ handler = callback; }} }});
const payload = {json.dumps(payload)};
const result = handler?.({{ payload }}) ?? payload;
console.log(JSON.stringify({{result, original: payload}}));
"""
    result = subprocess.run(
        ["bun", "-e", code], capture_output=True, text=True, check=True,
        env={**os.environ, "FM_OMP_HARNESS": "omp", "OMP_SKIP_SETUP": "1",
             "FM_OPUS_EFFORT_UNCAPPED": "", **environment},
    )
    observed = json.loads(result.stdout)
    assert observed["result"] == {**payload, "output_config": {"effort": expected, "format": "json"}}
    assert observed["original"] == payload
