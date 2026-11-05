import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "blueprint/fleet/browsers/fleet-browser"


def _home(tmp_path, cookies):
    home = tmp_path / "home"
    (home / ".fleet-browser").mkdir(parents=True)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "systemctl.calls"
    stub = stubs / "systemctl"
    stub.write_text(f'#!/bin/sh\necho "$@" >> {calls}\n')
    stub.chmod(0o755)
    jar = home / ".fleet-browser/cookies.json"
    if cookies is not None:
        jar.write_text(json.dumps({f"c{i}": {} for i in range(cookies)}))
    env = {**os.environ, "HOME": str(home), "PATH": f"{stubs}:{os.environ['PATH']}",
           "VOXL_GUARD_SECS": "0.2", "VOXL_JAR_WAIT_SECS": "1"}
    return home, jar, calls, env


@pytest.mark.parametrize("after,stopped", [(96, False), (120, False), (94, True), (0, True)])
def test_guard_stops_voxl_only_when_the_jar_count_falls(tmp_path, after, stopped):
    home, jar, calls, env = _home(tmp_path, 100)
    guard = subprocess.Popen([str(SCRIPT), "_voxl-guard"], env=env)
    try:
        time.sleep(0.6)
        jar.write_text(json.dumps({f"c{i}": {} for i in range(after)}))
        time.sleep(1.0)
        assert (guard.poll() is not None) == stopped
    finally:
        guard.kill()
        guard.wait()
    if stopped:
        assert calls.read_text().strip() == "--user stop fleet-browser-voxl.service"
        assert f"fell from 100 to {after} cookies" in (home / ".fleet-browser/fleet-browser.log").read_text()
    else:
        assert not calls.exists()


def test_guard_keeps_voxl_through_a_slow_decline_from_cookie_expiry(tmp_path):
    home, jar, calls, env = _home(tmp_path, 200)
    guard = subprocess.Popen([str(SCRIPT), "_voxl-guard"], env=env)
    try:
        for count in range(198, 158, -2):
            time.sleep(0.25)
            jar.write_text(json.dumps({f"c{i}": {} for i in range(count)}))
        assert guard.poll() is None and not calls.exists()
    finally:
        guard.kill()
        guard.wait()


def test_guard_ignores_a_jar_that_cannot_be_read_for_a_moment(tmp_path):
    home, jar, calls, env = _home(tmp_path, 100)
    guard = subprocess.Popen([str(SCRIPT), "_voxl-guard"], env=env)
    try:
        time.sleep(0.6)
        jar.write_text('{"c0": ')
        time.sleep(0.7)
        assert guard.poll() is None and not calls.exists()
    finally:
        guard.kill()
        guard.wait()


@pytest.mark.parametrize("cookies,expected", [(5, 0), (None, 1)])
def test_voxl_waits_for_the_cookie_jar(tmp_path, cookies, expected):
    _, _, _, env = _home(tmp_path, cookies)
    result = subprocess.run([str(SCRIPT), "_wait-jar"], env=env, capture_output=True, text=True)
    assert result.returncode == expected
    assert ("no cookie jar" in result.stderr) == (expected == 1)


def _tailscale_stub(tmp_path, certs, serve):
    state = tmp_path / "serve.json"
    state.write_text(json.dumps(serve))
    log = tmp_path / "tailscale.calls"
    stub = tmp_path / "bin/tailscale"
    stub.parent.mkdir()
    status = {"BackendState": "Running", "Self": {"DNSName": "box.example.ts.net."},
              "CertDomains": ["box.example.ts.net"] if certs else []}
    stub.write_text(f"""#!{sys.executable}
import json, sys
a = sys.argv[1:]
open({str(log)!r}, "a").write(" ".join(a) + "\\n")
if a[:2] == ["status", "--json"]:
    print(json.dumps({status!r}))
elif a[:3] == ["serve", "status", "--json"]:
    print(open({str(state)!r}).read())
elif a[:2] == ["serve", "--bg"]:
    port = a[2].split("=")[1]
    json.dump({{"Web": {{"box.example.ts.net:" + port: {{"Handlers": {{"/": {{"Proxy": a[3]}}}}}}}}}}, open({str(state)!r}, "w"))
""")
    stub.chmod(0o755)
    return stub.parent, log


def _apply_serve(tmp_path, path):
    playbook = tmp_path / "serve.yml"
    playbook.write_text(
        "- hosts: localhost\n  connection: local\n  gather_facts: false\n  tasks:\n"
        f"    - ansible.builtin.import_tasks: {ROOT}/blueprint/ansible/tasks/fleet-browser-serve.yml\n")
    return subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
         "-e", json.dumps({"crewship_fleet_browser_voxl_web_port": 6913, "ansible_become": False})],
        env={**os.environ, "PATH": f"{path}:{os.environ['PATH']}"}, capture_output=True, text=True)


def test_tailnet_publication_is_idempotent_and_keeps_other_services(tmp_path):
    path, log = _tailscale_stub(tmp_path, certs=True, serve={})
    first = _apply_serve(tmp_path, path)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "serve --bg --https=6913 http://127.0.0.1:6913" in log.read_text()
    assert "changed=1" in first.stdout
    second = _apply_serve(tmp_path, path)
    assert "changed=0" in second.stdout and log.read_text().count("serve --bg") == 1


def test_tailnet_port_serving_something_else_stops_the_apply(tmp_path):
    other = {"Web": {"box.example.ts.net:6913": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9"}}}}}
    path, log = _tailscale_stub(tmp_path, certs=True, serve=other)
    result = _apply_serve(tmp_path, path)
    assert result.returncode != 0 and "already uses HTTPS port 6913" in result.stdout + result.stderr
    assert "serve --bg" not in log.read_text()


def test_no_tailnet_certificates_means_no_serve_call(tmp_path):
    path, log = _tailscale_stub(tmp_path, certs=False, serve={})
    result = _apply_serve(tmp_path, path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "serve" not in log.read_text()
