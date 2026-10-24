"""The desk helpers the V2 front desk builds on: voice word order, exact-output clauses and secret values."""

import json
import shutil

import pytest
from test_imessage import DESK, bun

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

SOURCE = "The build is paused."


def voice(question, rewritten, preserve_words, answer=SOURCE):
    return bun(f"""
import {{ voiceAnswer }} from {DESK};
const out = voiceAnswer({{ answer: {json.dumps(answer)}, identity: false }}, {json.dumps(question)}, true,
  {json.dumps(rewritten)}, {json.dumps(preserve_words)});
console.log(JSON.stringify(out ?? null));
""")


@pytest.mark.parametrize("rewritten,kept", [
    ("The build is paused.", True),
    ("So the build is paused.", True),
    ("The paused build is.", False),
    ("The build is paused and the deploy failed.", False),
])
def test_word_order_guard_rejects_reordered_or_extended_voice(rewritten, kept):
    assert (voice("What is the status?", rewritten, True) is not None) is kept


def test_word_order_guard_is_off_by_default():
    assert voice("What is the status?", "The paused build is.", False) is not None


def test_exact_output_with_a_read_step_still_counts_as_exact():
    answer = "run-tool inspect --json"
    assert voice("Open the file and return the exact command.", answer, False, answer) == [answer]


def test_exact_output_after_other_work_is_not_exact():
    answer = "run-tool inspect --json"
    assert voice("Restart the service then return the exact command.", "The command is " + answer, False, answer) != [answer]


def test_secret_values_collects_only_credential_variables():
    values = bun(f"""
import {{ deskSecretValues }} from {DESK};
console.log(JSON.stringify(deskSecretValues({{ INCEPTION_API_KEY: "key-1234567890", PATH: "/usr/bin", HOME: "/x" }})));
""")
    assert "key-1234567890" in values
    assert "/usr/bin" not in values
