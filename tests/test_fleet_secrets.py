"""super.env sync pieces with fake values: chunk round trip, Worker auth, fetch script.

The Worker runs under Node with a stubbed Access certs endpoint and an RSA key made per run.
"""

import http.server
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
WORKER = ROOT / "apps/fleet-secrets"
FAKE_ENV = (
    "# fake super.env\n"
    "A=plain value with = and # inside\n"
    'QUOTED="double quoted"\n'
    "SINGLE='single'\n"
    "\n"
    "DUP=first\n"
    "#DEAD=commented values stay in the file\n"
    'LONE="unbalanced\n'
    "DUP=last \u00e9\n"
    "FLEET_SECRETS_ACCESS_CLIENT_ID=client-1\n"
    "NO_NEWLINE=end"
)
# More than 100 variables, multibyte characters and CRLF lines: larger than one secret.
BIG_ENV = (
    "".join(f"VAR_{i}='value {i} \u00e9\u20ac\U0001f600 {'x' * (i % 97)}'\r\n" for i in range(1500))
    + "FLEET_SECRETS_ACCESS_CLIENT_ID=client-1"
)

HARNESS = """
import { readFileSync } from "node:fs";
import worker from "%s";
const { chunks, vars } = JSON.parse(readFileSync(0, "utf8"));
const algo = { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" };
const gen = () => crypto.subtle.generateKey(
  { ...algo, modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]) }, true,
  ["sign", "verify"]);
const [good, evil] = [await gen(), await gen()];
const jwk = { ...(await crypto.subtle.exportKey("jwk", good.publicKey)), kid: "k1" };
globalThis.fetch = async (url) => {
  if (url !== "https://team.example/cdn-cgi/access/certs") throw new Error(url);
  return Response.json({ keys: [jwk] });
};
const b64 = (b) => Buffer.from(b).toString("base64url");
async function jwt(claims, key = good.privateKey) {
  const head = b64(JSON.stringify({ alg: "RS256", kid: "k1" }));
  const body = b64(JSON.stringify(claims));
  const sig = await crypto.subtle.sign(algo, key, new TextEncoder().encode(`${head}.${body}`));
  return `${head}.${body}.${b64(sig)}`;
}
const env = { team_domain: "team.example", aud: "aud-1",
  FLEET_SECRETS_ACCESS_CLIENT_ID: { get: async () => vars.FLEET_SECRETS_ACCESS_CLIENT_ID } };
chunks.forEach((c, i) => { env[`super_env_${i}`] = { get: async () => c }; });
const now = Date.now() / 1000;
const ok = { iss: "https://team.example", aud: ["aud-1"], exp: now + 60, nbf: now - 1,
  common_name: "client-1" };
const cases = {
  valid: await jwt(ok),
  none: null,
  garbage: "a.b.c",
  wrong_aud: await jwt({ ...ok, aud: ["other"] }),
  wrong_client: await jwt({ ...ok, common_name: "other" }),
  email_identity: await jwt({ ...ok, common_name: undefined, email: "x@example.com" }),
  wrong_issuer: await jwt({ ...ok, iss: "https://evil.example" }),
  expired: await jwt({ ...ok, exp: now - 1 }),
  not_yet: await jwt({ ...ok, nbf: now + 60 }),
  wrong_key: await jwt(ok, evil.privateKey),
};
const out = {};
for (const [name, token] of Object.entries(cases)) {
  const headers = token ? { "Cf-Access-Jwt-Assertion": token } : {};
  const r = await worker.fetch(new Request("https://x/", { headers }), env);
  out[name] = { status: r.status, cache: r.headers.get("cache-control"), body: await r.text() };
}
const post = new Request("https://x/", { method: "POST",
  headers: { "Cf-Access-Jwt-Assertion": cases.valid } });
out.post = { status: (await worker.fetch(post, env)).status };
console.log(JSON.stringify(out));
"""


def split(text: str) -> dict:
    result = subprocess.run(
        ["jq", "-Rs", "-f", WORKER / "split.jq"],
        input=text.encode(),
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_split_keeps_each_variables_last_assignment_without_quotes():
    assert split(FAKE_ENV)["vars"] == {
        "A": "plain value with = and # inside",
        "QUOTED": "double quoted",
        "SINGLE": "single",
        "LONE": '"unbalanced',
        "DUP": "last \u00e9",
        "NO_NEWLINE": "end",
        "FLEET_SECRETS_ACCESS_CLIENT_ID": "client-1",
    }


def test_split_cuts_a_large_file_into_chunks_one_secret_can_hold():
    chunks = split(BIG_ENV)["chunks"]
    assert len(chunks) > 1
    assert all(0 < len(c.encode()) <= 65536 for c in chunks)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
@pytest.mark.parametrize("text", [FAKE_ENV, BIG_ENV], ids=["small", "big"])
def test_worker_serves_exact_file_only_to_the_service_token(text):
    harness = HARNESS % (WORKER / "index.js").as_uri()
    result = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        input=json.dumps(split(text)),
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(result.stdout)
    assert out["valid"] == {"status": 200, "cache": "no-store", "body": text}
    for name, r in out.items():
        if name != "valid":
            assert r["status"] == 403, name
            assert r.get("body", "") == "", name


class Fake(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        good = (
            self.headers["CF-Access-Client-Id"] == "fake-id"
            and self.headers["CF-Access-Client-Secret"] == "fake-secret"
        )
        body = FAKE_ENV.encode() if good else b"denied"
        self.send_response(200 if good else 403)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/"
    httpd.shutdown()


def fetch(tmp_path: Path, url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [ROOT / "scripts/fetch-secrets.sh"],
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "FLEET_SECRETS_URL": url},
        capture_output=True,
        text=True,
    )


def test_fetch_writes_mode_600_from_credentials_file(tmp_path, server):
    creds = tmp_path / ".config/fleet-secrets.env"
    creds.parent.mkdir()
    creds.write_text(
        "FLEET_SECRETS_ACCESS_CLIENT_ID=fake-id\nFLEET_SECRETS_ACCESS_CLIENT_SECRET=fake-secret"
    )
    creds.chmod(0o644)
    assert fetch(tmp_path, server).returncode != 0
    assert not (tmp_path / "super.env").exists()

    creds.chmod(0o600)
    result = fetch(tmp_path, server)
    assert result.returncode == 0, result.stderr
    dest = tmp_path / "super.env"
    assert dest.read_text() == FAKE_ENV
    assert dest.stat().st_mode & 0o777 == 0o600
    assert "fake-secret" not in result.stdout + result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == [".config", "super.env"]


def test_fetch_failure_leaves_existing_file(tmp_path, server):
    creds = tmp_path / ".config/fleet-secrets.env"
    creds.parent.mkdir()
    creds.write_text(
        "FLEET_SECRETS_ACCESS_CLIENT_ID=fake-id\nFLEET_SECRETS_ACCESS_CLIENT_SECRET=wrong\n"
    )
    creds.chmod(0o600)
    dest = tmp_path / "super.env"
    dest.write_text("OLD=1\n")
    result = fetch(tmp_path, server)
    assert result.returncode != 0
    assert "403" in result.stderr
    assert dest.read_text() == "OLD=1\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".config", "super.env"]


class FakeCloudflare(http.server.BaseHTTPRequestHandler):
    """Secrets Store API with the 100-secret cap; `store` maps name -> {id, comment, value}."""

    store: dict
    calls: list
    prefix = "/secrets_store/stores/store-1/secrets"
    static = {
        "/access/organizations": {"auth_domain": "team.example"},
        "/access/apps": [{"domain": "fleet-secrets.iterative.sh", "aud": "aud-1"}],
        "/secrets_store/stores": [{"id": "store-1"}],
    }

    def reply(self, result=None, errors=None, status=200):
        body = json.dumps({"success": errors is None, "result": result, "errors": errors}).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_any(self):
        path = self.path.split("?")[0].split("/accounts/acct", 1)[1]
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if path.startswith(self.prefix):
            return self.secrets(path[len(self.prefix) + 1 :], raw)
        if path.startswith("/workers/"):
            self.calls.append((self.command, path))
            return self.reply({})
        self.reply(self.static[path])

    def secrets(self, sid, raw):
        if self.command == "GET":
            return self.reply(
                [{"name": n, "id": s["id"], "comment": s["comment"]} for n, s in self.store.items()]
            )
        if self.command == "POST":
            return self.create(json.loads(raw))
        name = next((n for n, s in self.store.items() if s["id"] == sid), None)
        if name is None:
            return self.reply(errors=[{"code": 10000, "message": "not found"}], status=404)
        self.calls.append((self.command, name))
        if self.command == "DELETE":
            del self.store[name]
        else:
            self.store[name]["value"] = json.loads(raw)["value"]
        self.reply({})

    def create(self, new):
        self.calls.append(("POST", [s["name"] for s in new]))
        if len(self.store) + len(new) > 100:
            return self.reply(
                errors=[{"code": 1003, "message": "maximum_secrets_exceeded"}], status=400
            )
        for s in new:
            self.store[s["name"]] = {
                "id": f"id-{s['name']}",
                "comment": s["comment"],
                "value": s["value"],
            }
        self.reply([])

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = handle_any

    def log_message(self, *args):
        pass


def run_stow(tmp_path: Path, old_secrets: int, token: str) -> subprocess.CompletedProcess:
    """Run stow-secrets.sh against the fake store; curl's argv lands in tmp_path/argv."""
    (tmp_path / "super.env").write_text(
        f"CLOUDFLARE_ACCOUNT_ID=acct\nCF_API_TOKEN_GLOBAL={token}\n{BIG_ENV}"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sleep").write_text("#!/bin/sh\n")
    (bin_dir / "curl").write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" >>{tmp_path}/argv\nexec {shutil.which("curl")} "$@"\n'
    )
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    FakeCloudflare.calls = []
    FakeCloudflare.store = {
        f"OLD_{i}": {"id": f"id-old-{i}", "comment": "super.env", "value": "x"}
        for i in range(old_secrets)
    }
    FakeCloudflare.store["KEEP"] = {"id": "id-keep", "comment": "other", "value": "x"}
    FakeCloudflare.store["FLEET_SECRETS_ACCESS_CLIENT_ID"] = {
        "id": "id-client",
        "comment": "super.env",
        "value": "old",
    }
    httpd = http.server.HTTPServer(("127.0.0.1", 0), FakeCloudflare)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        return subprocess.run(
            [ROOT / "scripts/stow-secrets.sh"],
            env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "HOME": str(tmp_path),
                "CF_API_BASE": f"http://127.0.0.1:{httpd.server_port}",
            },
            capture_output=True,
            text=True,
        )
    finally:
        httpd.shutdown()


@pytest.mark.skipif(not shutil.which("jq") or not shutil.which("curl"), reason="needs jq and curl")
@pytest.mark.parametrize("old_secrets, full", [(98, True), (10, False)], ids=["full", "roomy"])
def test_stow_makes_room_in_a_full_store_before_creating_chunks(tmp_path, old_secrets, full):
    token = "fake-token-value-123"
    result = run_stow(tmp_path, old_secrets, token)
    assert result.returncode == 0, result.stderr

    store = FakeCloudflare.store
    chunks = sorted(n for n in store if n.startswith("super_env_"))
    assert len(chunks) > 1
    assert sorted(store) == sorted(["KEEP", "FLEET_SECRETS_ACCESS_CLIENT_ID", *chunks])
    assert store["KEEP"]["value"] == "x"
    assert store["FLEET_SECRETS_ACCESS_CLIENT_ID"]["value"] == "client-1"

    mutations = [
        c for c in FakeCloudflare.calls if c[0] in ("POST", "DELETE") and "workers" not in c[1]
    ]
    first_post = next(i for i, c in enumerate(mutations) if c[0] == "POST")
    room = 100 - (old_secrets + 2)
    expected_early = max(0, len(chunks) - room)
    assert (expected_early > 0) == full
    assert first_post == expected_early
    assert all(c[0] == "DELETE" for c in mutations[:first_post])
    deleted = [c[1] for c in mutations if c[0] == "DELETE"]
    assert sorted(deleted) == sorted(f"OLD_{i}" for i in range(old_secrets))

    argv = (tmp_path / "argv").read_text()
    values = [token, *(s["value"] for s in store.values())]
    assert not any(v in argv or v in result.stdout + result.stderr for v in values if len(v) > 1)
