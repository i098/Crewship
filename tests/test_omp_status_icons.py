"""blueprint/config/omp-status-icons.ts, run under bun with a fake omp extension API.

omp's `status` segment strips every escape sequence from extension statuses
and paints the whole segment in one color, so a mode's state has to show in
the text itself, not in its styling: an off mode's icon is left out.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CAVEMAN, ADHD, PONYTAIL = "\uf066", "\U000f09d1", "\uf0c4"

# Stand-in for caveman's src/hooks/caveman-parse.js with the same contract:
# {action: "clear"} turns caveman off, {action: "set", mode} sets a level.
PARSER = """
exports.parseModeChange = (p) => {
  p = p.trim().toLowerCase();
  if (p === "stop caveman" || p === "normal mode") return { action: "clear" };
  if (p === "/caveman off") return { action: "set", mode: "off" };
  if (p === "talk like caveman") return { action: "set", mode: "full" };
  return null;
};
"""

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


def install_caveman(home: Path) -> None:
    plugin = home / "plugin"
    (plugin / "src/hooks").mkdir(parents=True)
    (plugin / "src/hooks/caveman-parse.js").write_text(PARSER)
    (home / ".omp/plugins").mkdir(parents=True)
    (home / ".omp/plugins/installed_plugins.json").write_text(
        json.dumps({"plugins": {"caveman@caveman": [{"installPath": str(plugin)}]}})
    )


def row(
    home: Path,
    statuses=None,
    prompt="",
    branch=(),
    inputs=(),
    end_branch=None,
    end_event="agent_end",
) -> str:
    """The icons row as omp's status segment shows it after the given events."""
    ext = json.dumps(str(ROOT / "blueprint/config/omp-status-icons.ts"))
    ctx = f"{{ hasUI: true, cwd: {json.dumps(str(home))}, ui, getSystemPrompt: async () => {json.dumps(prompt)}, sessionManager: {{ getBranch: () => branch }} }}"
    code = f"""
import ext from {ext};
const shown = {{}};
const ui = {{ theme: {{ fg: (c, s) => `\\x1b[2m${{s}}\\x1b[22m` }}, setStatus(k, t) {{ shown[k] = t; }} }};
let branch = {json.dumps(list(branch))};
const on = {{}};
ext({{ on: (e, f) => (on[e] = f) }});
const ctx = {ctx};
await on.session_start({{}}, ctx);
for (const [k, t] of Object.entries({json.dumps(statuses or {})})) ui.setStatus(k, t ?? undefined);
for (const text of {json.dumps(list(inputs))}) on.input({{ text, source: "interactive" }}, ctx);
const end = {json.dumps(end_branch)};
if (end) {{ branch = end; on[{json.dumps(end_event)}]({{}}, ctx); }}
console.log(JSON.stringify(shown["aa-modes"] ?? ""));
"""
    out = subprocess.run(
        ["bun", "-e", code],
        capture_output=True,
        text=True,
        check=True,
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
    )
    return re.sub(r"\x1b\[[0-9;]*m", "", json.loads(out.stdout))


def user(text: str) -> dict:
    return {
        "type": "message",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


SKILL = {"type": "custom_message", "customType": "skill-prompt", "details": {"name": "caveman"}}


def test_plugin_modes_show_only_while_their_plugin_reports_them_on(tmp_path):
    shown = row(tmp_path, {"ponytail": "🐴 ponytail: ⚡ FULL", "i-have-adhd": None})
    assert PONYTAIL in shown
    assert ADHD not in shown
    shown = row(tmp_path, {"ponytail": "", "i-have-adhd": "● ADHD ON"})
    assert ADHD in shown
    assert PONYTAIL not in shown


def test_ponytail_stays_shown_while_idle(tmp_path):
    # ponytail FULL shows "○" between turns; only mode off sends "".
    assert PONYTAIL in row(tmp_path, {"ponytail": "🐴 ponytail: ○"})


def test_caveman_is_off_without_the_plugin_even_when_a_rule_names_it(tmp_path):
    assert CAVEMAN not in row(tmp_path, prompt="read skill://caveman")


def test_caveman_follows_the_system_prompt_and_the_session_prompts(tmp_path):
    install_caveman(tmp_path)
    assert CAVEMAN not in row(tmp_path)
    assert CAVEMAN in row(tmp_path, prompt="keep skill://caveman in force")
    rule = "keep skill://caveman in force"
    assert CAVEMAN not in row(tmp_path, prompt=rule, inputs=["stop caveman"])
    assert CAVEMAN not in row(tmp_path, prompt=rule, inputs=["/caveman off"])
    assert CAVEMAN in row(tmp_path, prompt=rule, inputs=["stop caveman", "talk like caveman"])
    # A resumed session replays its own prompts.
    assert CAVEMAN not in row(tmp_path, prompt=rule, branch=[user("stop caveman")])


def test_a_caveman_skill_invocation_turns_it_on_at_turn_end(tmp_path):
    install_caveman(tmp_path)
    rule = "keep skill://caveman in force"
    before = [user("stop caveman")]
    assert CAVEMAN not in row(tmp_path, prompt=rule, branch=before, end_branch=before)
    assert CAVEMAN in row(tmp_path, prompt=rule, branch=before, end_branch=[*before, SKILL])
    assert CAVEMAN not in row(
        tmp_path, prompt=rule, branch=before, end_branch=[*before, SKILL, user("normal mode")]
    )


def test_a_caveman_skill_invocation_with_off_turns_it_off(tmp_path):
    install_caveman(tmp_path)
    rule = "keep skill://caveman in force"
    off = {**SKILL, "details": {"name": "caveman", "args": "off"}}
    assert CAVEMAN not in row(tmp_path, prompt=rule, end_branch=[off])
    assert CAVEMAN in row(tmp_path, prompt=rule, end_branch=[off, SKILL])


def test_tree_navigation_resyncs_caveman_to_the_new_branch(tmp_path):
    install_caveman(tmp_path)
    rule = "keep skill://caveman in force"
    before = [user("stop caveman")]
    assert CAVEMAN in row(
        tmp_path, prompt=rule, branch=before, end_branch=[], end_event="session_tree"
    )
