"""apps/signal/signal_bridge.py: parsing, sender filter, secrets file, redaction. Never a real Signal account."""

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

BRIDGE = Path(__file__).parents[1] / "apps/signal/signal_bridge.py"
spec = importlib.util.spec_from_file_location("signal_bridge", BRIDGE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

ME = "+15550001111"
VALUE = "p@ss'w0rd $HOME `id` \"q\" \\ ünï"


def envelope(text, source=ME, destination=ME, **sent):
    body = {"destinationNumber": destination, "message": text, **sent}
    return {"sourceNumber": source, "syncMessage": {"sentMessage": body}}


def receive(env):
    return json.dumps({"jsonrpc": "2.0", "method": "receive", "params": {"envelope": env}})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("secret A=b", ("A", "b")),
        ("secret GH_TOKEN_2=x y=z", ("GH_TOKEN_2", "x y=z")),
        ("secret NAME=" + VALUE, ("NAME", VALUE)),
        ("secret a=b", None),
        ("secret 1A=b", None),
        ("secret _A=b", None),
        ("secret A=", None),
        ("secret A b", None),
        ("Secret A=b", None),
        (" secret A=b", None),
        ("secret A=b\n", None),
        ("secret A=b\nexport EVIL=1", None),
        ("secret A=b\0c", None),
    ],
)
def test_parse_secret_takes_only_the_exact_form(text, expected):
    assert bridge.parse_secret(text) == expected


@pytest.mark.parametrize(
    ("env", "accepted"),
    [
        (envelope("hi"), True),
        (envelope("hi", destination="+15550002222"), False),  # sent to someone else
        (envelope("hi", source="+15550002222", destination="+15550002222"), False),  # their note to self
        (envelope("hi", groupInfo={"groupId": "g"}), False),
        ({"sourceNumber": ME, "dataMessage": {"message": "hi"}}, False),  # received, not sent
        ({"sourceNumber": "+15550002222", "dataMessage": {"message": "hi"}}, False),
        ({"sourceNumber": ME, "syncMessage": {"sentMessage": {"destinationNumber": ME}}}, False),
        ({}, False),
    ],
)
def test_only_a_note_to_self_from_the_account_passes(env, accepted):
    assert (bridge.note_to_self(env, ME) is not None) is accepted


def test_account_may_be_an_aci():
    env = {"sourceUuid": "u-1", "syncMessage": {"sentMessage": {"destinationUuid": "u-1", "message": "m"}}}
    assert bridge.note_to_self(env, "u-1") == "m"
    assert bridge.note_to_self(env, "u-2") is None


def test_value_round_trips_through_a_real_shell(tmp_path):
    secrets = tmp_path / "super.env"
    bridge.write_secret(secrets, "TOKEN", VALUE)
    shown = subprocess.run(
        ["bash", "-c", f'. "{secrets}"; printf %s "$TOKEN"'], capture_output=True, text=True, check=True
    )
    assert shown.stdout == VALUE


def test_save_replaces_one_name_and_keeps_every_other_byte(tmp_path):
    secrets = tmp_path / "super.env"
    head = b"# keys\r\nA=1\nexport OLD='x'\n\nexport  KEY=\"old\"\nKEYS=keep\nZ=\xff\xfe"
    secrets.write_bytes(head)
    secrets.chmod(0o644)
    bridge.write_secret(secrets, "KEY", "new")
    expected = head.replace(b'export  KEY="old"\n', b"export KEY='new'\n") + b"\nexport NEW='n'\n"
    bridge.write_secret(secrets, "NEW", "n")
    assert secrets.read_bytes() == expected
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o600
    assert sorted(os.listdir(tmp_path)) == ["super.env"]


def test_save_creates_the_file_mode_600_and_follows_a_symlink(tmp_path):
    real = tmp_path / "store/real.env"
    real.parent.mkdir()
    link = tmp_path / "super.env"
    link.symlink_to(real)
    bridge.write_secret(link, "A", "1")
    assert link.is_symlink() and real.read_text() == "export A='1'\n"
    assert stat.S_IMODE(real.stat().st_mode) == 0o600


def test_failed_write_leaves_the_file_and_no_temp_file(tmp_path, monkeypatch):
    secrets = tmp_path / "super.env"
    secrets.write_text("A=1\n")

    def refuse(*_):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(bridge.os, "replace", refuse)
    with pytest.raises(OSError):
        bridge.write_secret(secrets, "B", VALUE)
    assert secrets.read_text() == "A=1\n"
    assert os.listdir(tmp_path) == ["super.env"]


FAKE = """\
#!{python}
import json, sys
log = open({log!r}, "a")
for env in json.load(open({script!r})):
    print(json.dumps({{"jsonrpc": "2.0", "method": "receive", "params": {{"envelope": env}}}}), flush=True)
print("not json", flush=True)
for _ in range({replies}):
    log.write(sys.stdin.readline())
    log.flush()
"""


def run_bridge(tmp_path, envelopes, secrets, replies=1):
    """The real bridge against a fake signal-cli that replays `envelopes` and records its stdin."""
    cli = tmp_path / "signal-cli"
    sent = tmp_path / "sent.jsonl"
    script = tmp_path / "script.json"
    script.write_text(json.dumps(envelopes))
    cli.write_text(
        FAKE.format(python=sys.executable, log=str(sent), script=str(script), replies=replies)
    )
    cli.chmod(0o755)
    done = subprocess.run(
        [sys.executable, BRIDGE, "--account", ME, "--secrets-file", secrets, "--signal-cli", cli],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30,
    )
    return done, sent


def test_bridge_saves_the_note_replies_with_the_key_and_prints_no_value(tmp_path):
    secrets = tmp_path / "super.env"
    secrets.write_text("KEEP=1\n")
    other_chat = envelope("secret LEAK=other-chat-value", destination="+15550002222")
    done, sent = run_bridge(tmp_path, [other_chat, envelope(f"secret API_KEY={VALUE}")], secrets)
    assert done.returncode == 1  # the fake signal-cli ended
    assert secrets.read_text().startswith("KEEP=1\nexport API_KEY='p@ss")
    assert "LEAK" not in secrets.read_text()
    request = json.loads(sent.read_text())
    assert request["method"] == "send"
    assert request["params"] == {"noteToSelf": True, "message": "saved API_KEY"}
    for output in (done.stdout, done.stderr):
        assert VALUE not in output and "other-chat-value" not in output and "ünï" not in output
    assert "saved API_KEY" in done.stderr


def test_a_failed_save_sends_no_reply_and_logs_no_value(tmp_path):
    missing = tmp_path / "no-such-dir/super.env"
    done, sent = run_bridge(tmp_path, [envelope(f"secret API_KEY={VALUE}")], missing, replies=0)
    assert not sent.exists() or sent.read_text() == ""
    assert "dropped a message" in done.stderr and "FileNotFoundError" in done.stderr
    assert VALUE not in done.stdout + done.stderr and "ünï" not in done.stderr
    assert "API_KEY" not in done.stderr
