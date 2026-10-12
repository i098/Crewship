import grp
import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def run_model_merge(home, check=False, local_bin=None):
    playbook = home / "merge.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost",
        "connection": "local",
        "gather_facts": False,
        "vars": {
            "ansible_become": False,
            "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
            "crewship_local_bin": str(local_bin or Path(shutil.which("bun")).parent),
            "crewship_cfg": {"home": str(home), "user": pwd.getpwuid(os.getuid()).pw_name},
            "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        },
        "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/omp_models.yml")}],
    }]))
    return subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,",
         str(playbook), *(["--check"] if check else [])],
        cwd=home, env={**os.environ, "HOME": str(home)}, capture_output=True, text=True,
    )


def merge_models(home, check=False):
    result = run_model_merge(home, check=check)
    assert result.returncode == 0, result.stdout + result.stderr
    return int(result.stdout.rsplit("changed=", 1)[1].split()[0])


def read_models(target):
    home = target.parents[2]
    result = subprocess.run(
        [shutil.which("bun"), "--eval",
         'import { YAML } from "bun"; console.log(JSON.stringify(YAML.parse(await Bun.stdin.text())));'],
        input=target.read_text(), cwd=home, env={**os.environ, "HOME": str(home)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("sources", [
    (), ("yml",), ("yaml",), ("json",), ("yaml", "json"),
    ("yml", "yaml"), ("yml", "json"), ("yml", "yaml", "json"),
])
def test_model_merge_keeps_user_entries_and_is_idempotent(tmp_path, sources):
    target = tmp_path / ".omp/agent/models.yml"
    target.parent.mkdir(parents=True)
    custom = {"providers": {
        "private-provider": {
            "baseUrl": "https://example.com/path//keep?value=/*literal*/",
            "models": [{"id": 'local/*literal*/"quoted"\\path//keep'}],
            "headers": {
                "X-Revision": "1e3", "X-Octal": "0o10", "X-Logging": "off",
                "X-Url": "https://example.com/path//keep?value=/*literal*/",
            },
        },
        "openai-codex": {
            "models": [{"id": "user-model"}],
            "modelOverrides": {
                "user-model": {"contextWindow": 64000},
                "gpt-6.1-sol": {"contextWindow": 64000, "maxTokens": 8192},
            },
        },
    }}
    originals = {}
    for extension in sources:
        source = target.with_suffix(f".{extension}")
        entry = {"providers": {
            **custom["providers"],
            "source": {"baseUrl": f"https://{extension}.example.com"},
        }}
        source.write_text(
            "{ // legacy provider configuration\n/* keep user fields */\n"
            + json.dumps(entry)[1:-1] + ",\n}\n"
            if extension == "json" else json.dumps(entry)
        )
        originals[source] = source.read_bytes()
    before = target.read_bytes() if target.exists() else None
    assert merge_models(tmp_path, check=True) == 1
    assert (target.read_bytes() if target.exists() else None) == before
    assert all(source.read_bytes() == content for source, content in originals.items())
    assert merge_models(tmp_path) == 1
    merged = read_models(target)
    shipped = yaml.safe_load((ROOT / "blueprint/config/omp-models.yml").read_text())
    overrides = merged["providers"]["openai-codex"]["modelOverrides"]
    for model, values in shipped["providers"]["openai-codex"]["modelOverrides"].items():
        assert overrides[model].items() >= values.items()
    if sources:
        assert merged["providers"]["source"] == {"baseUrl": f"https://{sources[0]}.example.com"}
        assert merged["providers"]["private-provider"] == custom["providers"]["private-provider"]
        assert merged["providers"]["openai-codex"]["models"] == [{"id": "user-model"}]
        assert overrides["user-model"] == {"contextWindow": 64000}
        assert overrides["gpt-6.1-sol"]["maxTokens"] == 8192
    assert target.stat().st_mode & 0o777 == 0o600
    written = target.read_bytes()
    assert merge_models(tmp_path) == 0
    assert target.read_bytes() == written
    assert read_models(target) == merged
    assert all(source.read_bytes() == content for source, content in originals.items()
               if source != target)


@pytest.mark.parametrize("extension", ["yaml", "json"])
def test_model_merge_migrates_even_when_overrides_are_already_present(tmp_path, extension):
    target = tmp_path / ".omp/agent/models.yml"
    target.parent.mkdir(parents=True)
    shipped = yaml.safe_load((ROOT / "blueprint/config/omp-models.yml").read_text())
    source = target.with_suffix(f".{extension}")
    source.write_text(json.dumps(shipped) if extension == "json" else yaml.safe_dump(shipped))
    original = source.read_bytes()
    assert merge_models(tmp_path, check=True) == 1
    assert not target.exists()
    assert source.read_bytes() == original
    assert merge_models(tmp_path) == 1
    assert read_models(target) == shipped
    written = target.read_bytes()
    assert merge_models(tmp_path) == 0
    assert target.read_bytes() == written
    assert read_models(target) == shipped
    assert source.read_bytes() == original


@pytest.mark.parametrize("extension", ["yml", "yaml"])
def test_yaml_model_merge_preserves_unquoted_string_scalars(tmp_path, extension):
    target = tmp_path / ".omp/agent/models.yml"
    target.parent.mkdir(parents=True)
    source = target.with_suffix(f".{extension}")
    source.write_text(
        "providers:\n"
        "  openai-codex:\n"
        "    headers:\n"
        "      X-Off: off\n"
        "      X-On: on\n"
        "      X-Yes: yes\n"
        "      X-No: no\n"
        "      X-Date: 2026-10-10\n"
        '      X-Revision: "1e3"\n'
        '      X-Octal: "0o10"\n'
        "    models:\n"
        "      - id: user-model\n"
        "    modelOverrides:\n"
        "      gpt-6.1-sol:\n"
        "        contextWindow: 64000\n"
        "        maxTokens: 8192\n"
    )
    original = source.read_bytes()
    assert merge_models(tmp_path, check=True) == 1
    assert source.read_bytes() == original
    assert target.exists() == (extension == "yml")
    assert merge_models(tmp_path) == 1
    merged = read_models(target)
    provider = merged["providers"]["openai-codex"]
    assert provider["headers"] == {
        "X-Off": "off", "X-On": "on", "X-Yes": "yes", "X-No": "no", "X-Date": "2026-10-10",
        "X-Revision": "1e3", "X-Octal": "0o10",
    }
    assert provider["models"] == [{"id": "user-model"}]
    assert provider["modelOverrides"]["gpt-6.1-sol"] == {
        "contextWindow": 272000, "maxContextWindow": 1000000, "maxTokens": 8192,
    }
    written = target.read_bytes()
    assert merge_models(tmp_path) == 0
    assert target.read_bytes() == written
    assert read_models(target) == merged
    if source != target:
        assert source.read_bytes() == original


@pytest.mark.parametrize("extension", [None, "yml", "yaml", "json"])
def test_model_preview_without_parser_preserves_files(tmp_path, extension):
    target = tmp_path / ".omp/agent/models.yml"
    target.parent.mkdir(parents=True)
    source = target.with_suffix(f".{extension}") if extension else None
    if source:
        source.write_text('{"providers": {"user": {"baseUrl": "https://example.com"}}}')
    original = source.read_bytes() if source else None
    missing_bin = tmp_path / ".local/bin"
    result = run_model_merge(tmp_path, check=True, local_bin=missing_bin)
    assert result.returncode == 0, result.stdout + result.stderr
    assert int(result.stdout.rsplit("changed=", 1)[1].split()[0]) == (0 if source else 1)
    assert target.exists() == (extension == "yml")
    if source:
        assert "Model merge preview requires Bun installation" in result.stdout
        assert source.read_bytes() == original
        result = run_model_merge(tmp_path, local_bin=missing_bin)
        assert result.returncode != 0
        assert source.read_bytes() == original
        assert target.exists() == (extension == "yml")


def test_shipped_model_configuration_schema():
    from jsonschema import validate

    window = {"type": "integer", "minimum": 1}
    validate(yaml.safe_load((ROOT / "blueprint/config/omp-models.yml").read_text()), {
        "type": "object", "required": ["providers"], "additionalProperties": False,
        "properties": {"providers": {
            "type": "object", "required": ["openai-codex"], "additionalProperties": False,
            "properties": {"openai-codex": {
                "type": "object", "required": ["modelOverrides"], "additionalProperties": False,
                "properties": {"modelOverrides": {
                    "type": "object", "minProperties": 1,
                    "additionalProperties": {
                        "type": "object", "required": ["contextWindow", "maxContextWindow"],
                        "additionalProperties": False,
                        "properties": {"contextWindow": window, "maxContextWindow": window},
                    },
                }},
            }},
        }},
    })
    dispatch = json.loads((ROOT / "blueprint/config/crew-dispatch.json").read_text())
    for tier in [dispatch["default"], *(rule["use"] for rule in dispatch["rules"])]:
        assert isinstance(tier, list)
        for model in tier:
            assert set(model) == {"harness", "model", "provider"}
            assert model["harness"] == "omp"
            assert model["provider"] in {"claude", "codex"}
