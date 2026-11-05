import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "blueprint/maintenance/discord"
loader = importlib.machinery.SourceFileLoader("discord_cli", str(SOURCE))
discord = importlib.util.module_from_spec(importlib.util.spec_from_loader("discord_cli", loader))
loader.exec_module(discord)


@pytest.fixture
def login(tmp_path, monkeypatch):
    path = tmp_path / "credentials.toml"
    path.write_text(
        'selected_account = "2"\n[[accounts]]\nid = "1"\ntoken = "one"\n[[accounts]]\nid = "2"\ntoken = "two"\n'
    )
    path.chmod(0o600)
    monkeypatch.setattr(discord, "CREDENTIALS", path)
    return path


def test_token_is_the_selected_account(login):
    assert discord.token() == "two"


def test_token_refuses_a_readable_file(login):
    login.chmod(0o644)
    with pytest.raises(SystemExit, match="mode 600"):
        discord.token()


def test_send_dry_run_posts_nothing(login, monkeypatch, capsys):
    monkeypatch.setattr(discord, "call", lambda *a, **k: pytest.fail("network used"))
    discord.main(["send", "9", "hello", "--dry-run"])
    assert "dry run" in capsys.readouterr().out


def test_send_posts_json_to_the_channel(login, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(
        discord, "call", lambda path, body=None: seen.append((path, body)) or {"id": "5"}
    )
    discord.main(["send", "9", "hello"])
    assert seen == [("channels/9/messages", {"content": "hello"})]
    assert capsys.readouterr().out == "sent 5\n"


def test_http_error_never_echoes_the_token(login, monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 401, "x", {"Authorization": "two"}, None)

    monkeypatch.setattr(discord.urllib.request, "urlopen", boom)
    with pytest.raises(SystemExit) as error:
        discord.call("users/@me")
    assert "two" not in str(error.value)
