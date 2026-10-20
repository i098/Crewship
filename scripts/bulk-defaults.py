#!/usr/bin/env python3
"""Add missing native bulk defaults without rewriting user configuration."""

import argparse
import configparser
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


def check_config_links(path):
    for component in (path, *path.parents):
        if component.is_symlink() and not component.exists():
            raise FileNotFoundError(f"Unavailable configuration link: {component}")


def native_text(path, changes):
    check_config_links(path)
    path = path.resolve()
    if path in changes:
        return changes[path]
    return path.read_text() if os.path.lexists(path) else ""



def toml_default(text, section, key, value):
    current = tomllib.loads(text)
    for part in section.split(".") if section else []:
        current = current.get(part, {})
        if not isinstance(current, dict):
            return text
    if key in current:
        return text
    entry = f'{key} = {json.dumps(value)}\n'
    if not section:
        desired = entry + text
    else:
        header = re.search(r"(?m)^\[" + re.escape(section) + r"\][ \t]*(?:#.*)?$", text)
        if header:
            desired = text[:header.end()] + "\n" + entry + text[header.end():]
        else:
            desired = text.rstrip() + f"\n[{section}]\n" + entry
    tomllib.loads(desired)
    return desired


def rc_default(text, key, value):
    name = re.escape(key)
    option = re.compile(rf"""^(?:{name}|"{name}"|'{name}')\s*(?:=|[#;]|$)""")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            break
        if option.match(line):
            return text
    return f"{key}={value}\n" + text


def ini_default(text, section, key, value):
    if not section:
        return rc_default(text, key, value)
    parser = configparser.RawConfigParser()
    parser.read_string(text)
    if parser.has_option(section, key):
        return text
    entry = f"{key}={value}\n"
    offset = 0
    for line in text.splitlines(keepends=True):
        header = parser.SECTCRE.match(line.strip())
        if header and header["header"] == section:
            end = offset + len(line)
            separator = "" if line.endswith("\n") else "\n"
            return text[:end] + separator + entry + text[end:]
        offset += len(line)
    return text.rstrip() + f"\n[{section}]\n" + entry


def pip_config_files(home):
    dirs = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    files = [Path(d) / "pip/pip.conf" for d in dirs.split(":") if d]
    files += [Path("/etc/pip.conf"), home / ".pip/pip.conf", home / ".config/pip/pip.conf"]
    if os.environ.get("XDG_CONFIG_HOME"):
        files.append(Path(os.environ["XDG_CONFIG_HOME"]) / "pip/pip.conf")
    files.append(Path(sys.prefix) / "pip.conf")
    if os.environ.get("VIRTUAL_ENV"):
        files.append(Path(os.environ["VIRTUAL_ENV"]) / "pip.conf")
    if os.environ.get("PIP_CONFIG_FILE"):
        files.append(Path(os.environ["PIP_CONFIG_FILE"]))
    return files


def pip_cache_configured(home, changes):
    for path in pip_config_files(home):
        parser = configparser.RawConfigParser()
        target = path.resolve()
        if target in changes:
            parser.read_string(changes[target])
        else:
            parser.read(path)
        for section in parser.sections():
            if any(name.replace("_", "-").removeprefix("--") == "cache-dir"
                   for name in parser.options(section)):
                return True
    return False


def native_changes(home, data):
    changes = {}
    settings = [
        (".config/treehouse/config.toml", toml_default, "", "root", str(data)),
        (".npmrc", ini_default, "", "cache", str(data / "cache/npm")),
        (".config/pip/pip.conf", ini_default, "global", "cache-dir", str(data / "cache/pip")),
        (".bunfig.toml", toml_default, "install.cache", "dir", str(data / "cache/bun")),
        (".config/uv/uv.toml", toml_default, "", "cache-dir", str(data / "cache/uv")),
        (".config/pnpm/rc", ini_default, "", "store-dir", str(data / "cache/pnpm")),
    ]
    for relative, update, section, key, value in settings:
        if relative == ".config/pip/pip.conf" and pip_cache_configured(home, changes):
            continue
        if relative == ".config/pnpm/rc":
            legacy = native_text(home / ".npmrc", changes)
            if update(legacy, section, key, value) == legacy:
                continue
        path = home / relative
        text = native_text(path, changes)
        desired = update(text, section, key, value)
        if desired != text:
            changes[path.resolve()] = desired
    go = home / ".config/go/env"
    text = native_text(go, changes)
    desired = text
    for key, value in {"GOCACHE": data / "cache/go-build", "GOMODCACHE": data / "cache/go-mod"}.items():
        if not re.search(r"(?m)^" + key + "=", text):
            desired = desired.rstrip() + f"\n{key}={value}\n"
    if desired != text:
        changes[go.resolve()] = desired
    downloads = home / ".config/user-dirs.dirs"
    text = native_text(downloads, changes)
    if not re.search(r"(?m)^\s*XDG_DOWNLOAD_DIR=", text):
        changes[downloads.resolve()] = text.rstrip() + f'\nXDG_DOWNLOAD_DIR="{data}/downloads"\n'
    return changes


def write_native_file(path, content):
    check_config_links(path)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            if path.exists():
                metadata = path.stat()
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
                os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def private_dirs(data, check):
    caches = ("npm", "pip", "bun", "uv", "pnpm", "go-build", "go-mod", "deno", "bun-transpiler")
    paths = [data / "cache" / name for name in caches]
    missing = [path for path in paths if not os.path.lexists(path)]
    if not check:
        for path in missing:
            path.mkdir(mode=0o700)
    return bool(missing)


def configure(home, data, check=False):
    changes = native_changes(home, data)
    pnpm = shutil.which("pnpm")
    if pnpm:
        check_config_links(home / (os.environ.get("XDG_CONFIG_HOME") or ".config") / "pnpm/config.yaml")
    dirs_change = private_dirs(data, check)
    if not check:
        for path, content in changes.items():
            write_native_file(path, content)
    # pnpm 11 owns its YAML format. Query after the pnpm 10 rc update.
    pnpm_change = False
    if pnpm:
        result = subprocess.run(
            ["pnpm", "config", "get", "--json", "store-dir"],
            cwd=home, check=True, capture_output=True, text=True,
        )
        pnpm_change = not result.stdout.strip()
        if pnpm_change and not check:
            subprocess.run(
                ["pnpm", "config", "set", "store-dir", str(data / "cache/pnpm")],
                cwd=home, check=True, stdout=subprocess.DEVNULL,
            )
    return {"changed": bool(changes) or dirs_change or pnpm_change}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    os.environ["HOME"] = str(args.home)
    print(json.dumps(configure(args.home, args.data_dir, args.check)))


if __name__ == "__main__":
    main()
