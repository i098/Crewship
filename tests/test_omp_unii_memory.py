"""blueprint/config/omp-unii-memory.ts with apps/imessage/memory.ts beside it, run under bun: the view returns after a compaction."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


def test_view_returns_after_compaction(tmp_path):
    ext = tmp_path / "fm-unii-memory.ts"
    ext.write_text((ROOT / "blueprint/config/omp-unii-memory.ts").read_text())
    (tmp_path / "fm-unii-memory").mkdir()
    shutil.copy(ROOT / "apps/imessage/memory.ts", tmp_path / "fm-unii-memory/memory.ts")
    code = f"""
import ext from {json.dumps(str(ext))};
const h = {{}};
ext({{ on: (n, f) => (h[n] = f), registerTool: () => {{}}, zod: {{ object: () => ({{}}), number: () => ({{ int: () => ({{}}) }}) }} }});
const ctx = {{ agent: {{ kind: "main" }}, sessionManager: {{ getBranch: () => [], getSessionId: () => "s1" }} }};
h.session_start({{}}, ctx);
h.message_end({{ message: {{ role: "user", content: "the vault code is PLUM-4471" }} }}, ctx);
const before = await h.before_agent_start({{}}, ctx);
h.session_compact();
const after = await h.before_agent_start({{}}, ctx);
console.log(JSON.stringify({{ before: before ?? null, view: after?.message?.content ?? "" }}));
"""
    out = subprocess.run(["bun", "-e", code], capture_output=True, text=True, check=True, env={"PATH": str(Path(shutil.which("bun")).parent), "FM_HOME": str(tmp_path / "home")})
    got = json.loads(out.stdout)
    assert got["before"] is None
    assert "PLUM-4471" in got["view"]
    assert any((tmp_path / "home/state/unii/s1").glob("**/*.jsonl")), "the log must sit in a per-session directory"
