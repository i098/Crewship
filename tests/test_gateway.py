"""blueprint/maintenance/crewship-gateway: password, allow window, lockout, cookie and header trust."""

import http.client
import importlib.machinery
import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "blueprint/maintenance/crewship-gateway"
loader = importlib.machinery.SourceFileLoader("crewship_gateway", str(SCRIPT))
spec = importlib.util.spec_from_loader("crewship_gateway", loader)
gw = importlib.util.module_from_spec(spec)
loader.exec_module(gw)

DAY = 24 * 3600
T0 = 1_800_000_000.0


@pytest.fixture
def gate(tmp_path):
    secrets = tmp_path / "super.env"
    secrets.write_text("OTHER=keep\n")
    gate = gw.Gate(secrets, tmp_path / "state/gateway.json", DAY)
    gate.set_hash(gw.hash_password("right-pass"))
    return gate


def test_hash_lives_in_secrets_file_beside_other_keys(gate):
    text = gate.secrets_file.read_text()
    assert "OTHER=keep" in text and "right-pass" not in text
    assert gate.secrets_file.stat().st_mode & 0o777 == 0o600


def test_right_password_admits_ip_for_the_window(gate):
    assert gate.login("203.0.113.5", "right-pass", T0)
    assert gate.admitted("203.0.113.5", None, T0 + DAY - 1)
    assert not gate.admitted("203.0.113.5", None, T0 + DAY)
    assert not gate.admitted("203.0.113.6", None, T0)


def test_wrong_password_admits_nothing(gate):
    assert gate.login("203.0.113.5", "wrong", T0) is None
    assert gate.login("203.0.113.5", "", T0) is None
    assert not gate.admitted("203.0.113.5", None, T0)


def test_no_stored_hash_refuses_every_password(tmp_path):
    gate = gw.Gate(tmp_path / "super.env", tmp_path / "state.json", DAY)
    assert gate.login("203.0.113.5", "", T0) is None
    assert gate.login("203.0.113.5", "anything", T0) is None


def test_lockout_after_five_wrong_then_release(gate):
    ip = "203.0.113.5"
    for i in range(gw.MAX_FAILURES):
        assert gate.login(ip, "wrong", T0 + i) is None
    assert gate.locked_for(ip, T0 + 5) > 0
    assert gate.login(ip, "right-pass", T0 + 10) is None  # even the right password
    assert not gate.admitted(ip, None, T0 + 10)
    assert gate.login("198.51.100.7", "right-pass", T0 + 10)  # other addresses are unaffected
    later = T0 + 4 + gw.LOCK_SECONDS
    assert gate.locked_for(ip, later) == 0
    assert gate.login(ip, "right-pass", later)


def test_old_failures_are_forgotten(gate):
    ip = "203.0.113.5"
    for i in range(gw.MAX_FAILURES - 1):
        gate.login(ip, "wrong", T0 + i)
    assert gate.login(ip, "wrong", T0 + gw.LOCK_SECONDS + 10) is None
    assert gate.locked_for(ip, T0 + gw.LOCK_SECONDS + 10) == 0


def test_cookie_admits_a_new_address_until_it_expires(gate):
    cookie = gate.login("203.0.113.5", "right-pass", T0)
    assert gate.admitted("198.51.100.9", cookie, T0 + DAY - 1)
    assert not gate.admitted("198.51.100.9", cookie, T0 + DAY)
    issued, signature = cookie.split(".")
    assert not gate.admitted("198.51.100.9", f"{int(issued) + DAY * 1000}.{signature}", T0 + DAY + 5)
    assert not gate.admitted("198.51.100.9", f"{issued}.{'0' * 64}", T0)
    assert not gate.admitted("198.51.100.9", "garbage", T0)


def test_revoke_all_signs_out_addresses_and_cookies(gate):
    cookie = gate.login("203.0.113.5", "right-pass", T0)
    gate.revoke(T0 + 1)
    assert not gate.admitted("203.0.113.5", None, T0 + 2)
    assert not gate.admitted("198.51.100.9", cookie, T0 + 2)
    assert gate.login("203.0.113.5", "right-pass", T0 + 3)


def test_revoke_one_address_keeps_the_others(gate):
    gate.login("203.0.113.5", "right-pass", T0)
    gate.login("203.0.113.6", "right-pass", T0)
    gate.revoke(T0 + 1, "203.0.113.5")
    assert not gate.admitted("203.0.113.5", None, T0 + 2)
    assert gate.admitted("203.0.113.6", None, T0 + 2)


def test_new_password_voids_old_cookies(gate):
    cookie = gate.login("203.0.113.5", "right-pass", T0)
    gate.set_hash(gw.hash_password("next-pass"))
    assert not gate.admitted("198.51.100.9", cookie, T0 + 1)
    assert gate.login("203.0.113.5", "right-pass", T0 + 1) is None


def test_generated_password_is_typeable_and_checks(gate):
    secret = gw.new_password()
    assert len(secret) == 23 and set(secret) <= set(gw.ALPHABET + "-")
    assert gw.check_password(secret, gw.hash_password(secret))
    assert not gw.check_password(secret, "not-a-hash")


def test_login_redirect_stays_on_this_site():
    assert gw.safe_next("/9525/board?x=1") == "/9525/board?x=1"
    for target in ("//evil.example/", "/\\evil.example/", "https://evil.example/", "", "/a b"):
        assert gw.safe_next(target) == "/"


def test_client_ip_trusts_only_cf_connecting_ip():
    assert gw.client_ip({"CF-Connecting-IP": " 2001:db8::1 "}) == "2001:db8::1"
    assert gw.client_ip({"X-Forwarded-For": "203.0.113.5"}) is None
    assert gw.client_ip({"CF-Connecting-IP": "203.0.113.5, 10.0.0.1"}) is None


# --- the server on loopback, in front of a stub upstream ----------------------


@pytest.fixture
def stack(gate, tmp_path):
    seen = []

    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(dict(self.headers))
            if self.path == "/go":
                self.send_response(302)
                self.send_header("Location", "/there")
            else:
                self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 0), gw.Handler)
    server.gate = gate
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def request(method, url, headers=None, body=None):
        connection = http.client.HTTPConnection(*server.server_address)
        connection.request(method, url, body, headers or {})
        response = connection.getresponse()
        return response, response.read().decode()

    yield request, upstream.server_address[1], seen
    upstream.shutdown()
    server.shutdown()


def test_server_rejects_requests_without_the_tunnel_header(stack):
    request, port, seen = stack
    response, _ = request("GET", f"/{port}/", {"X-Forwarded-For": "203.0.113.5"})
    assert response.status == 400 and not seen


def test_server_login_cookie_and_proxy(stack, gate):
    request, port, seen = stack
    ip = {"CF-Connecting-IP": "203.0.113.5"}
    response, body = request("GET", f"/{port}/", ip)
    assert response.status == 401 and 'name="password"' in body and not seen
    form = f"password=right-pass&next=/{port}/"
    response, _ = request("POST", "/_gateway/login", {**ip, "Content-Type": "application/x-www-form-urlencoded"}, form)
    assert response.status == 303 and response.getheader("Location") == f"/{port}/"
    cookie = response.getheader("Set-Cookie")
    for attribute in ("HttpOnly", "Secure", "SameSite=Strict", f"Max-Age={DAY}", "Path=/"):
        assert attribute in cookie
    value = cookie.split(";")[0]
    # A new address with the cookie is admitted; the cookie itself never reaches the app.
    response, body = request("GET", f"/{port}/x", {"CF-Connecting-IP": "198.51.100.9", "Cookie": f"app=1; {value}"})
    assert (response.status, body) == (200, "ok")
    assert seen[-1]["Cookie"] == "app=1"
    response, _ = request("GET", f"/{port}/go", ip)
    assert response.getheader("Location") == f"/{port}/there"


def test_server_wrong_password_then_lockout(stack):
    request, port, _ = stack
    headers = {"CF-Connecting-IP": "203.0.113.5", "Content-Type": "application/x-www-form-urlencoded"}
    statuses = [request("POST", "/_gateway/login", headers, "password=nope")[0].status for _ in range(gw.MAX_FAILURES)]
    assert statuses == [401] * (gw.MAX_FAILURES - 1) + [429]
    assert request("POST", "/_gateway/login", headers, "password=right-pass")[0].status == 429


def test_server_logout_forgets_the_address(stack):
    request, port, _ = stack
    headers = {"CF-Connecting-IP": "203.0.113.5", "Content-Type": "application/x-www-form-urlencoded"}
    assert request("POST", "/_gateway/login", headers, "password=right-pass")[0].status == 303
    assert request("GET", f"/{port}/", headers)[0].status == 200
    response, _ = request("POST", "/_gateway/logout", headers, "")
    assert "Max-Age=0" in response.getheader("Set-Cookie")
    assert request("GET", f"/{port}/", headers)[0].status == 401
