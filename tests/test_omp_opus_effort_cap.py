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
@pytest.mark.parametrize("location", ["request", "message", "both"])
def test_provider_effort_cap(environment, model, effort, expected, location):
    extension = json.dumps(str(ROOT / "blueprint/config/omp-opus-effort-cap.ts"))
    message = {"role": "system", "content": []}
    expected_message = dict(message)
    if location in ("message", "both"):
        message["output_config"] = {"effort": effort, "format": "json"}
        expected_message["output_config"] = {"effort": expected, "format": "json"}
    messages = [
        message,
        {"role": "assistant", "content": "OK", "output_config": {"effort": "low"}},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "output_config": {
            "effort": effort if location in ("request", "both") else "medium",
            "format": "json",
        },
    }
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
    assert observed["result"] == {
        **payload,
        "messages": [expected_message, messages[1]],
        "output_config": {
            "effort": expected if location in ("request", "both") else "medium",
            "format": "json",
        },
    }
    assert observed["original"] == payload
