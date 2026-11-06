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


def _geonode_env(tmp_path, **over):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GEONODE_")}
    return {**env, "FLEET_SECRETS_FILE": str(tmp_path / "none"), **over}


GEONODE = {"GEONODE_GATEWAY": "127.0.0.1", "GEONODE_USERNAME": "u", "GEONODE_PASSWORD": "s3cret",
           "GEONODE_STICKY_PORT_BASE": "30000", "GEONODE_STICKY_PORT_MAX": "30009"}
PROXY = ROOT / "blueprint/fleet/browsers/geonode-proxy.py"


def test_geonode_check_names_only_missing_variables(tmp_path):
    r = subprocess.run([sys.executable, str(PROXY), "--check"], env=_geonode_env(tmp_path, GEONODE_PASSWORD="s3cret"),
                       capture_output=True, text=True)
    assert r.returncode != 0 and "GEONODE_GATEWAY" in r.stderr and "s3cret" not in r.stderr


def test_geonode_settings_fall_back_to_the_secrets_file(tmp_path):
    f = tmp_path / "super.env"
    f.write_text("".join(f"export {k}='{v}'\n" for k, v in GEONODE.items()))
    r = subprocess.run([sys.executable, str(PROXY), "--check"], env=_geonode_env(tmp_path, FLEET_SECRETS_FILE=str(f)))
    assert r.returncode == 0


def test_geonode_proxy_adds_credentials_to_connect(tmp_path):
    import asyncio
    import base64
    import importlib.util

    spec = importlib.util.spec_from_file_location("geonode_proxy", PROXY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen = []

    async def upstream(reader, writer):
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        writer.write(b"pong")
        await writer.drain()
        writer.close()

    async def run():
        up = await asyncio.start_server(upstream, "127.0.0.1", 0)
        up_port = up.sockets[0].getsockname()[1]
        auth = base64.b64encode(b"u:s3cret")
        front = await asyncio.start_server(mod.serve_client("127.0.0.1", up_port, auth), "127.0.0.1", 0)
        r, w = await asyncio.open_connection("127.0.0.1", front.sockets[0].getsockname()[1])
        w.write(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
        data = await asyncio.wait_for(r.read(), 5)
        w.close()
        up.close()
        front.close()
        return data

    data = asyncio.run(run())
    assert data.endswith(b"pong")
    assert seen[0].startswith(b"CONNECT example.com:443 HTTP/1.1\r\n")
    assert b"Proxy-Authorization: Basic " + base64.b64encode(b"u:s3cret") in seen[0]


def test_up_proxy_refuses_without_geonode_settings(tmp_path):
    home, _, _, env = _home(tmp_path, 1)
    r = subprocess.run([str(SCRIPT), "up", "chrome", "--proxy"],
                       env=_geonode_env(tmp_path, **{k: env[k] for k in ("HOME", "PATH")}), capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "GEONODE_*" in r.stderr
    assert not (home / ".fleet-browser/proxy-chrome").exists()


def test_a_tier_goes_direct_unless_its_proxy_flag_is_set(tmp_path):
    home, _, _, env = _home(tmp_path, 1)
    run = tmp_path / "run"
    run.mkdir()
    (run / "fleet-browser").write_text(SCRIPT.read_text())
    (run / "fleet-browser").chmod(0o755)
    (run / "obscura").write_text('#!/bin/sh\necho "$@"\n')
    (run / "obscura").chmod(0o755)
    base = _geonode_env(tmp_path, **{k: env[k] for k in ("HOME", "PATH")})
    direct = subprocess.run([str(run / "fleet-browser"), "_run-obscura"], env=base, capture_output=True, text=True, timeout=30)
    assert "--proxy" not in direct.stdout and "--port 9222" in direct.stdout
    (home / ".fleet-browser/proxy-obscura").touch()
    refused = subprocess.run([str(run / "fleet-browser"), "_run-obscura"], env=base, capture_output=True, text=True, timeout=30)
    assert refused.returncode == 1 and "GEONODE_*" in refused.stderr
