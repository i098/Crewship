"""blueprint/maintenance/crewship-gateway: password, allow window, lockout, cookie and header trust."""

import http.client
import importlib.machinery
import importlib.util
import socket
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
    gate = gw.Gate(tmp_path / "gateway/password.hash", tmp_path / "state/gateway.json", DAY)
    gate.set_hash(gw.hash_password("right-pass"))
    return gate


def test_hash_lives_in_a_private_host_file(gate):
    assert gate.hash_file.read_text().startswith("scrypt$")
    assert "right-pass" not in gate.hash_file.read_text()
    assert gate.hash_file.stat().st_mode & 0o777 == 0o600
    assert gate.hash_file.parent.stat().st_mode & 0o777 == 0o700


def test_password_goes_to_a_file_never_to_stdout(tmp_path, monkeypatch, capsys):
    hash_file = tmp_path / "gateway/password.hash"
    monkeypatch.setenv("CREWSHIP_GATEWAY_HASH", str(hash_file))
    monkeypatch.setenv("CREWSHIP_GATEWAY_STATE", str(tmp_path / "state/gateway.json"))
    initial = hash_file.with_name("initial-password")
    assert gw.main(["password", "--if-missing"]) == 0
    assert capsys.readouterr().out.strip() == str(initial)
    secret = initial.read_text().strip()
    assert initial.stat().st_mode & 0o777 == 0o600
    assert gw.check_password(secret, hash_file.read_text().strip())
    assert gw.main(["password", "--if-missing"]) == 0
    assert capsys.readouterr().out == "" and initial.read_text().strip() == secret
    assert gw.main(["password"]) == 0
    assert capsys.readouterr().out.strip() == str(initial)
    assert initial.read_text().strip() != secret
    assert gw.check_password(initial.read_text().strip(), hash_file.read_text().strip())


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
    gate = gw.Gate(tmp_path / "password.hash", tmp_path / "state.json", DAY)
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


def test_parallel_guesses_get_no_more_than_the_limit(gate):
    checked = []
    real = gw.check_password

    def slow(password, stored):
        checked.append(password)
        threading.Event().wait(0.05)
        return real(password, stored)

    gw.check_password = slow
    try:
        threads = [threading.Thread(target=gate.login, args=("203.0.113.5", f"guess{i}", T0)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        gw.check_password = real
    assert len(checked) == gw.MAX_FAILURES
    assert gate.locked_for("203.0.113.5", T0) > 0


def test_password_checks_run_at_most_two_at_a_time(gate):
    running, peak, lock = [0], [0], threading.Lock()
    real = gw.check_password

    def slow(password, stored):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        threading.Event().wait(0.05)
        with lock:
            running[0] -= 1
        return real(password, stored)

    gw.check_password = slow
    try:
        threads = [threading.Thread(target=gate.login, args=(f"2001:db8::{i}", "guess", T0)) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        gw.check_password = real
    assert peak[0] == 2


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
            seen.append({"path": self.path, **dict(self.headers)})
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


def test_server_logout_signs_out_every_device(stack):
    request, port, _ = stack
    headers = {"CF-Connecting-IP": "203.0.113.5", "Content-Type": "application/x-www-form-urlencoded"}
    response = request("POST", "/_gateway/login", headers, "password=right-pass")[0]
    assert response.status == 303
    cookie = response.getheader("Set-Cookie").split(";")[0]
    other = {"CF-Connecting-IP": "203.0.113.6", "Content-Type": "application/x-www-form-urlencoded"}
    assert request("POST", "/_gateway/login", other, "password=right-pass")[0].status == 303
    phone = {"CF-Connecting-IP": "198.51.100.9", "Cookie": cookie}
    assert request("GET", f"/{port}/", phone)[0].status == 200
    stranger = {"CF-Connecting-IP": "192.0.2.50", "Content-Type": "application/x-www-form-urlencoded"}
    response, body = request("POST", "/_gateway/logout", stranger, "")
    assert response.status == 401 and 'name="next" value="/"' in body
    cross_site = {**headers, "Sec-Fetch-Site": "cross-site"}
    assert request("POST", "/_gateway/logout", cross_site, "")[0].status == 403
    for visitor in (headers, other, phone):
        assert request("GET", f"/{port}/", visitor)[0].status == 200
    response, _ = request("POST", "/_gateway/logout", phone, "")
    assert "Max-Age=0" in response.getheader("Set-Cookie")
    for visitor in (headers, other, phone):
        assert request("GET", f"/{port}/", visitor)[0].status == 401


def test_root_absolute_asset_follows_the_referer_port(stack):
    request, port, seen = stack
    ip = {"CF-Connecting-IP": "203.0.113.5", "Host": "x.trycloudflare.com"}
    asset = {**ip, "Referer": f"https://x.trycloudflare.com/{port}/"}
    assert request("GET", "/@vite/client", asset)[0].status == 401 and not seen
    request("POST", "/_gateway/login", {**ip, "Content-Type": "application/x-www-form-urlencoded"}, "password=right-pass")
    response, body = request("GET", "/@vite/client?v=1", asset)
    assert (response.status, body, seen[-1]["path"]) == (200, "ok", "/@vite/client?v=1")
    elsewhere = {**ip, "Referer": f"https://evil.example/{port}/"}
    assert request("GET", "/@vite/client", elsewhere)[0].status == 404
    assert 'action="/_gateway/logout"' in request("GET", "/", ip)[1]


def test_numeric_app_path_with_nothing_on_that_port_stays_on_the_page_port(stack):
    request, port, seen = stack
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    ip = {"CF-Connecting-IP": "203.0.113.5", "Host": "x.trycloudflare.com"}
    request("POST", "/_gateway/login", {**ip, "Content-Type": "application/x-www-form-urlencoded"}, "password=right-pass")
    link = {**ip, "Referer": f"https://x.trycloudflare.com/{port}/"}
    response, body = request("GET", f"/{closed}/hello", link)
    assert (response.status, body, seen[-1]["path"]) == (200, "ok", f"/{closed}/hello")
    assert request("GET", f"/{closed}/hello", ip)[0].status == 502


def test_root_absolute_asset_follows_the_last_port_cookie(stack):
    request, port, seen = stack
    ip = {"CF-Connecting-IP": "203.0.113.5"}
    request("POST", "/_gateway/login", {**ip, "Content-Type": "application/x-www-form-urlencoded"}, "password=right-pass")
    page = {**ip, "Sec-Fetch-Dest": "document"}
    response, _ = request("GET", f"/{port}/", page)
    remembered = [c for c in response.headers.get_all("Set-Cookie") if c.startswith(gw.PORT_COOKIE + "=")]
    assert remembered and all(a in remembered[0] for a in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/"))
    assert f"Max-Age={DAY}" in remembered[0]
    jar = {**ip, "Cookie": f"app=1; {remembered[0].split(';')[0]}"}
    response, body = request("GET", "/src/main.ts", {**jar, "Referer": "http://127.0.0.1/src/app.ts"})
    assert (response.status, body, seen[-1]["path"]) == (200, "ok", "/src/main.ts")
    assert seen[-1]["Cookie"] == "app=1"
    assert 'action="/_gateway/logout"' in request("GET", "/", jar)[1]
    assert request("GET", "/_gateway/other", jar)[0].status == 404


def test_sub_resource_never_changes_the_port_cookie(stack):
    request, port, _ = stack
    ip = {"CF-Connecting-IP": "203.0.113.5"}
    request("POST", "/_gateway/login", {**ip, "Content-Type": "application/x-www-form-urlencoded"}, "password=right-pass")
    for dest in ("script", "empty", "image", None):
        headers = {**ip, "Sec-Fetch-Dest": dest} if dest else ip
        response, _ = request("GET", f"/{port}/poll", headers)
        assert response.status == 200
        assert not any(c.startswith(gw.PORT_COOKIE + "=") for c in response.headers.get_all("Set-Cookie") or [])


def test_server_answers_400_for_a_bad_content_length(stack):
    request, _, _ = stack
    for value in ("abc", "-5"):
        response, _ = request("POST", "/_gateway/login", {"CF-Connecting-IP": "203.0.113.5", "Content-Length": value})
        assert response.status == 400
