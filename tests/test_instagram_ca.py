import configparser
import json
import os
import shlex
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from jinja2 import Environment, meta

ROOT = Path(__file__).parents[1]


def make_wheel(directory, name, version, dependencies=()):
    dist_info = f"{name}-{version}.dist-info"
    files = {
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {dependency}\n" for dependency in dependencies)
        ),
        f"{dist_info}/WHEEL": "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{name}/__init__.py": "",
    }
    files[f"{dist_info}/RECORD"] = "".join(f"{path},,\n" for path in files)
    wheel = directory / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)


@pytest.fixture
def dependency_index(tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    make_wheel(wheels, "pip", "26.2.1")
    make_wheel(wheels, "certifi", "2026.10.18")
    make_wheel(wheels, "instagrapi", "1.0.0", ("certifi>=2026.10.18",))
    uv = shutil.which("uv")
    environment = {
        **os.environ, "UV_NO_CONFIG": "1", "UV_NO_INDEX": "1", "UV_OFFLINE": "1",
        "UV_FIND_LINKS": str(wheels), "UV_CACHE_DIR": str(tmp_path / "cache"),
        "UV_PYTHON_DOWNLOADS": "never",
    }
    environment.pop("VIRTUAL_ENV", None)
    environment.pop("PYTHONPATH", None)
    environment.pop("UV_NO_PROJECT", None)
    base = tmp_path / "base"
    subprocess.run([uv, "venv", "--python", sys.executable, base], env=environment,
                   check=True, capture_output=True)
    subprocess.run([uv, "pip", "install", "--python", base / "bin/python",
                    "pip==26.2.1", "certifi==2026.10.18"], env=environment,
                   check=True, capture_output=True)
    environment.update(UV_PYTHON=str(base / "bin/python"), VIRTUAL_ENV=str(base))
    return uv, environment, wheels


@pytest.mark.parametrize("template", [
    "fm-insta-reply.j2", "instagram-dm-listen.service.j2",
    "instagram-dm-poll.service.j2", "instagram-reel-curator.service.j2",
])
def test_instagram_launchers_reject_old_certifi_and_do_not_inherit_pip(
    tmp_path, dependency_index, template,
):
    uv, environment, wheels = dependency_index
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "unrelated"\nversion = "1.0.0"\n'
        'dependencies = ["pip==26.2.1"]\n'
    )
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import importlib.metadata as m, json\n"
        "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions()}))\n"
    )
    source = (ROOT / "blueprint/ansible/templates" / template).read_text()
    jinja = Environment()
    jinja.filters.update(
        quote=shlex.quote, dirname=os.path.dirname, comment=lambda value: "# " + value,
    )
    variables = dict.fromkeys(meta.find_undeclared_variables(jinja.parse(source)), "unused")
    variables.update(
        crewship_uv_bin=uv, crewship_instagram_dm_backend="instagrapi",
        crewship_instagram_dm_script=str(probe), crewship_instagram_curator_script=str(probe),
        crewship_instagram_dm_session=str(tmp_path / "session.json"),
    )
    rendered = jinja.from_string(source).render(variables)
    if template.endswith("service.j2"):
        unit = configparser.ConfigParser(interpolation=None, strict=False)
        unit.read_string(rendered)
        command = shlex.split(unit["Service"]["ExecStart"])
    else:
        launcher = tmp_path / "reply"
        launcher.write_text(rendered)
        launcher.chmod(0o755)
        command = [str(launcher)]
    blocked = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert blocked.returncode != 0
    assert "certifi" in blocked.stderr
    make_wheel(wheels, "certifi", "2026.10.19")
    result = subprocess.run(
        command, cwd=tmp_path, env=environment, check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == {"instagrapi": "1.0.0", "certifi": "2026.10.19"}
