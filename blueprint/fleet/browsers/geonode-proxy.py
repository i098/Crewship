#!/usr/bin/env python3
"""Local HTTP proxy on 127.0.0.1:<port> that forwards through one Geonode residential sticky session.

Chrome's --proxy-server cannot carry credentials, so this adds them. Settings come from the
GEONODE_* environment, else from the KEY=VALUE lines of $FLEET_SECRETS_FILE (default ~/super.env):
  GEONODE_GATEWAY, GEONODE_USERNAME, GEONODE_PASSWORD, GEONODE_STICKY_PORT_BASE, GEONODE_STICKY_PORT_MAX
One upstream port in BASE..MAX is picked at start, so the exit IP stays the same until the proxy stops.

  geonode-proxy.py --check    exit 0 when every setting is present and valid; print nothing
  geonode-proxy.py <port>     serve; the password is never printed
"""
import asyncio
import base64
import os
import random
import sys
from pathlib import Path

KEYS = ("GEONODE_GATEWAY", "GEONODE_USERNAME", "GEONODE_PASSWORD", "GEONODE_STICKY_PORT_BASE", "GEONODE_STICKY_PORT_MAX")


def settings(env, secrets_file):
    """The five GEONODE_* values, or exit naming only the missing variables."""
    values = {k: env.get(k, "").strip() for k in KEYS}
    if not all(values.values()) and Path(secrets_file).is_file():
        for line in Path(secrets_file).read_text().splitlines():
            key, _, val = line.removeprefix("export ").partition("=")
            if key.strip() in KEYS and not values[key.strip()]:
                values[key.strip()] = val.strip().strip("'\"")
    if missing := [k for k, v in values.items() if not v]:
        sys.exit(f"geonode-proxy: missing {', '.join(missing)}")
    try:
        base, top = int(values["GEONODE_STICKY_PORT_BASE"]), int(values["GEONODE_STICKY_PORT_MAX"])
    except ValueError:
        sys.exit("geonode-proxy: GEONODE_STICKY_PORT_BASE and GEONODE_STICKY_PORT_MAX must be port numbers")
    if not 0 < base <= top <= 65535:
        sys.exit("geonode-proxy: GEONODE_STICKY_PORT_BASE must be at most GEONODE_STICKY_PORT_MAX, both in 1-65535")
    return values


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


def serve_client(host, port, auth):
    async def handle(reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            up_reader, up_writer = await asyncio.open_connection(host, port)
        except (OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        first, _, rest = head.partition(b"\r\n")
        # Connection: close keeps a plain-HTTP client from reusing the link without credentials.
        extra = b"Proxy-Authorization: Basic " + auth + b"\r\n" + (b"" if first.startswith(b"CONNECT") else b"Connection: close\r\n")
        up_writer.write(first + b"\r\n" + extra + rest)
        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))

    return handle


async def main(listen_port, cfg):
    port = random.randint(int(cfg["GEONODE_STICKY_PORT_BASE"]), int(cfg["GEONODE_STICKY_PORT_MAX"]))
    auth = base64.b64encode(f"{cfg['GEONODE_USERNAME']}:{cfg['GEONODE_PASSWORD']}".encode())
    server = await asyncio.start_server(serve_client(cfg["GEONODE_GATEWAY"], port, auth), "127.0.0.1", listen_port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    cfg = settings(os.environ, os.environ.get("FLEET_SECRETS_FILE", str(Path.home() / "super.env")))
    if sys.argv[1:] == ["--check"]:
        sys.exit(0)
    asyncio.run(main(int(sys.argv[1]), cfg))
