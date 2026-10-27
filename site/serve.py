import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        route = urlsplit(path).path
        candidate = super().translate_path(route + ".html")
        if Path(candidate).is_file():
            return candidate
        return super().translate_path(path)

    def send_head(self):
        # Match Cloudflare's default auto-trailing-slash handling for HTML files.
        parsed = urlsplit(self.path)
        route = unquote(parsed.path)
        canonical = route.rstrip("/").removesuffix(".html").removesuffix("/index") or "/"
        html_file = Path(super().translate_path(canonical + ".html"))
        if route != canonical and (html_file.is_file() or canonical == "/"):
            self.send_response(307)
            self.send_header("Location", canonical + ("?" + parsed.query if parsed.query else ""))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        return super().send_head()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    handler = partial(Handler, directory=Path(__file__).with_name("dist"))
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Serving on http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
