import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "schedules", Path(__file__).parents[1] / "blueprint/maintenance/crewship-schedules.py"
)
schedules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedules)


def test_mixed_sources_preserve_identity_history_and_owner(tmp_path, monkeypatch):
    home = tmp_path / "orbit"
    home.mkdir()
    marker = home / ".fm-secondmate-home"
    marker.write_text("orbit-mate-a1\n")
    other = tmp_path / "nova"
    other.mkdir()
    (other / ".fm-secondmate-home").write_text("nova-mate-b2\n")
    home_alias = tmp_path / "orbit-alias"
    home_alias.symlink_to(home, target_is_directory=True)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/secondmates.md").write_text(
        f"- orbit-mate-a1 - Report owner (home: {home_alias}/../orbit; scope: Reports; projects: orbit; added 2026-10-21)\n"
        f"- nova-mate-b2 - Other owner (home: {other}/.; scope: Reports; projects: nova; added 2026-10-21)\n"
    )
    owners, errors = schedules.read_registry(tmp_path / "data/secondmates.md")
    assert not errors
    assert owners == {str(home): "orbit-mate-a1", str(other): "nova-mate-b2"}
    cron = schedules.cron_rows(
        "CRON_TZ=UTC\n# Purpose: Publish the report\n0 9 * * * /srv/orbit/bin/report\n"
        "@reboot /srv/orbital/bin/report\n"
        "* * * * * /usr/bin/printf hello%I'm awake\n"
        "0 3 * * * /srv/orbit/bin/report >> /var/log/nightly.log\n".replace("/srv/orbit", str(home)),
        "user cron", owners
    )
    system_cron = schedules.cron_rows(
        f"0 9 * * * root {home}/bin/report\n", "/etc/crontab", owners, True
    )
    commands = [
        (f"/usr/bin/find {home}/data -type f -delete", "find", "Unknown"),
        (f"/usr/bin/curl https://example.net/health >> {home}/health.log", "curl", "Unknown"),
        (f"/usr/bin/cat {home}/data.py", "cat", "Unknown"),
        (f"/usr/bin/echo '{home}/data.sh' ; /usr/bin/cat {other}/data.py", "echo", "Unknown"),
        (f"/usr/bin/python3 -u {home}/report.py {other}/data.py", "report.py", "orbit-mate-a1"),
        (f"/bin/sh -e {home}/report.sh {other}/data.sh", "report.sh", "orbit-mate-a1"),
        (f"/bin/sh -c '{home}/report.sh'", "sh", "Unknown"),
        (f"/usr/bin/python3 -c 'print(\"{home}\")'", "python3", "Unknown"),
        (f"/usr/bin/python3 -m package {home}/data.py", "python3", "Unknown"),
        (f"HOME={other} /usr/bin/python3 '{home}/report task.py'", "report task.py", "orbit-mate-a1"),
        (f"2>{other}/errors.log /bin/bash {home}/report.sh", "report.sh", "orbit-mate-a1"),
        (f"{home}/../foreign/report", "report", "Unknown"),
        (f"cd {home} && ./bin/report.sh", "report.sh", "orbit-mate-a1"),
        (f"cd {home} && python3 report.py {other}/data.py", "report.py", "orbit-mate-a1"),
        (f"cd {home} && /usr/bin/cat {other}/data.py", "cat", "orbit-mate-a1"),
        (f"cd {home} && /usr/bin/python3 {other}/report.py", "report.py", "Unknown"),
        (f"cd {home} ; ./bin/report.sh", "cd", "Unknown"),
        (f"cd {home} || ./bin/report.sh", "cd", "Unknown"),
        (f"cd {home}/$SUBDIR && ./bin/report.sh", "cd", "Unknown"),
        (f"/usr/bin/env HOME={home} /usr/bin/cat {home}/data.py", "env", "Unknown"),
        (f"{home_alias}/bin/report", "report", "orbit-mate-a1"),
        (f"/usr/bin/python3 {home}/$JOB.py", "$JOB.py", "Unknown"),
        (f"{home}/$RUNNER", "$RUNNER", "Unknown"),
        (f"/usr/bin/python3 {home}/${{JOB}}.py", "${JOB}.py", "Unknown"),
        (f'/usr/bin/python3 "{home}/$(printf report).py"', "$(printf report).py", "Unknown"),
        (f'/usr/bin/python3 "{home}/`printf report`.py"', "`printf report`.py", "Unknown"),
        (f"/usr/bin/python3 {home}/reports/*.py", "*.py", "Unknown"),
    ]
    for source, system in (("user cron", False), ("/etc/crontab", True), ("/etc/cron.d/report", True)):
        for command, name, owner in commands:
            item, = schedules.cron_rows(
                f"JOB=../nova/report\n0 9 * * * {'root ' if system else ''}{command}\n", source, owners, system
            )
            assert (item["name"], item["owner"], item["purpose"]) == (name, owner, f"Run {name}")
    timer, empty, running, success, skipped = schedules.properties(
        "Id=report.timer\nUnit=report.service\nActiveState=active\n"
        "TimersCalendar={ OnCalendar=daily ; next_elapse=Thu 2026-10-22 09:00:00 UTC }\n"
        "LastTriggerUSec=Wed 2026-10-21 09:00:00 UTC\n"
        "NextElapseUSecRealtime=Thu 2026-10-22 09:00:00 UTC\n\n"
        "Id=report.service\nActiveState=inactive\nResult=success\nExecMainCode=0\n"
        "ExecMainStatus=0\nExecMainStartTimestamp=\nExecMainExitTimestamp=\n\n"
        "Id=report.service\nActiveState=activating\nResult=success\nExecMainCode=1\n"
        "ExecMainStatus=2\nExecMainStartTimestamp=Wed 2026-10-21 09:00:01 UTC\n\n"
        "Id=report.service\nActiveState=inactive\nResult=success\nExecMainCode=1\n"
        "ExecMainStatus=2\nExecMainStartTimestamp=Wed 2026-10-21 09:00:01 UTC\n"
        "ExecMainExitTimestamp=Wed 2026-10-21 09:00:03 UTC\nSuccessExitStatus=2\n"
        "ExecStart={ path=/srv/orbit/bin/report ; argv[]=/srv/orbit/bin/report ; }\n\n"
        "Id=report.service\nActiveState=inactive\nSubState=dead\nResult=exec-condition\n"
        "ExecMainCode=0\nExecMainStatus=0\nExecMainStartTimestamp=\n"
        "ExecMainExitTimestamp=\n".replace("/srv/orbit", str(home))
    )
    assert cron[0]["owner"] == system_cron[0]["owner"] == "orbit-mate-a1"
    assert cron[1]["owner"] == "Unknown"
    assert cron[0]["purpose"] == "Publish the report"
    assert cron[0]["schedule"] == "0 9 * * * (CRON_TZ=UTC)"
    assert [r["name"] for r in cron[2:]] == ["printf", "report"]
    assert (cron[0]["next"], cron[0]["last"], cron[0]["result"]) == ("Unknown",) * 3
    assert schedules.timer_row(timer, empty, "user timer", owners)["result"] == "No record"
    assert schedules.timer_row(timer, running, "user timer", owners)["result"] == "Running"
    completed = schedules.timer_row(timer, success, "system timer", owners)
    assert {(r["name"], r["source"]) for r in [cron[0], system_cron[0], completed]} == {
        ("report", "user cron"), ("report", "/etc/crontab"), ("report", "system timer")
    }
    assert completed["result"] == "OK 2"
    assert completed["owner"] == "orbit-mate-a1"
    assert completed["last"] != completed["service"]["ExecMainExitTimestamp"]
    for source in ("user timer", "system timer"):
        for history in (skipped, dict(success, Result="exec-condition")):
            skipped_row = schedules.timer_row(timer, history, source, owners)
            assert skipped_row["result"] == "Skipped"
            assert schedules.result_kind(skipped_row["result"]) == "unknown"
            assert schedules.cell_value(dict(skipped_row, stale=False), "result") == "Skipped"
            assert skipped_row["last"] == timer["LastTriggerUSec"]
        no_main = schedules.timer_row(timer, skipped, source, owners)
        assert schedules.timestamp(no_main["service"]["ExecMainStartTimestamp"]) == "Unknown"
        assert schedules.timestamp(no_main["service"]["ExecMainExitTimestamp"]) == "Unknown"
        assert schedules.timer_row(timer, empty, source, owners)["result"] == "No record"
        assert schedules.timer_row(timer, {}, source, owners)["result"] == "No record"
        active = dict(skipped, ActiveState="activating")
        assert schedules.timer_row(timer, active, source, owners)["result"] == "Running"
        condition_failed = dict(skipped, ActiveState="failed", Result="exit-code")
        failure = schedules.timer_row(timer, condition_failed, source, owners)
        assert (failure["result"], schedules.result_kind(failure["result"])) == ("exit-code", "failed")
        data_command = dict(success, ExecStart=(
            f"{{ path=/usr/bin/curl ; argv[]=/usr/bin/curl {home}/data.py ; ignore_errors=no ; }}"
        ))
        assert schedules.timer_row(timer, data_command, source, owners)["owner"] == "Unknown"
        for key in ("FragmentPath", "WorkingDirectory"):
            service = dict(data_command, **{key: f"{home}/units/$literal"})
            assert schedules.timer_row(timer, service, source, owners)["owner"] == "orbit-mate-a1"
        unit = dict(timer, FragmentPath=f"{home}/units/$literal.timer")
        assert schedules.timer_row(unit, data_command, source, owners)["owner"] == "orbit-mate-a1"
        service = dict(success, ExecStart=(
            f"{{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -u {home}/report.py"
            f" {other}/data.py ; ignore_errors=no ; }}"
        ))
        assert schedules.timer_row(timer, service, source, owners)["owner"] == "orbit-mate-a1"
        for executable, arguments in (
            ("/usr/bin/python3", f"/usr/bin/python3 {home}/$JOB.py"),
            (f"{home}/$RUNNER", f"{home}/$RUNNER"),
            ("/usr/bin/python3", f'/usr/bin/python3 "{home}/$(printf report).py"'),
        ):
            service = dict(success, ExecStart=(
                f"{{ path={executable} ; argv[]={arguments} ; ignore_errors=no ; }}"
            ))
            assert schedules.timer_row(timer, service, source, owners)["owner"] == "Unknown"
    failed = dict(completed, name="broken", result="exit-code (1)", next="2026-10-23 09:00:00 UTC")
    earlier = dict(completed, name="earlier", next="2026-10-22 07:00:00 UTC")
    ordered = sorted([completed, earlier, failed], key=schedules.row_order)
    assert [item["name"] for item in ordered] == ["broken", "earlier", "report"]
    assert sorted([no_main, failed], key=schedules.row_order)[0] is failed
    assert schedules.text("report\x1b[31m\n\u202e") == r"report\x1b[31m\n\u202e"
    expected = {}
    for root, mode in ((tmp_path, 0o700), (home, 0o600), (other, 0o755)):
        (root / "state").mkdir()
        check = root / "state/report.check.sh"
        check.write_text("#!/bin/sh\nexit 17\n")
        check.chmod(mode)
        (root / "state/report.check-trust").write_text("Do not read this file")
        expected[str(check)] = (owners.get(str(root), "Unknown"), f"Metadata only; script {mode:04o}")
    extra = tmp_path / "state/pull-request.check.sh"
    extra.write_text("Do not read or run this file")
    extra.chmod(0o600)
    expected[str(extra)] = ("Unknown", "Metadata only; script 0600")
    literal_check = home / "state/$literal.check.sh"
    literal_check.write_text("Do not read or run this file")
    literal_check.chmod(0o700)
    expected[str(literal_check)] = ("orbit-mate-a1", "Metadata only; script 0700")
    home_checks = {path for path in expected if Path(path).parent == home / "state"}
    original_open, original_iterdir = Path.open, Path.iterdir
    original_read_text = Path.read_text
    scanned, unavailable, unreadable_metadata = set(), set(), set()

    def metadata_only_open(path, *args, **kwargs):
        assert path.parent.name != "state", f"Read check contents: {path}"
        return original_open(path, *args, **kwargs)

    def list_directory(path):
        if str(path) == "/etc/cron.d":
            return iter(())
        assert path in {root / "state" for root in (tmp_path, home, other)}
        scanned.add(path)
        if path in unavailable:
            raise PermissionError("State directory unavailable")
        return original_iterdir(path)

    def read_text(path, *args, **kwargs):
        if path in unreadable_metadata:
            raise PermissionError("Home metadata unavailable")
        return "" if str(path) == "/etc/crontab" else original_read_text(path, *args, **kwargs)

    def run(argv):
        if argv == ["crontab", "-l"]:
            return ""
        assert argv in (
            ["systemctl", "list-timers", "--all", "--no-pager", "--output=json"],
            ["systemctl", "--user", "list-timers", "--all", "--no-pager", "--output=json"],
        )
        return "[]"

    monkeypatch.setattr(Path, "open", metadata_only_open)
    monkeypatch.setattr(Path, "iterdir", list_directory)
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(schedules, "run", run)
    registry = tmp_path / "data/secondmates.md"
    snapshot = schedules.collect_snapshot(tmp_path, registry, {})
    assert not snapshot["errors"]
    checks = [item for item in snapshot["rows"] if item["source"].startswith("home check: ")]
    assert {item["path"]: (item["owner"], item["registration"]) for item in checks} == expected
    assert all(item["result"] == "Unknown" and not item["stale"] for item in checks)
    assert all(item["schedule"] == "Watcher sweep (default 5m)" for item in checks)
    assert scanned == {root / "state" for root in (tmp_path, home, other)}
    monkeypatch.chdir(home)
    for selected in (None, home, Path("."), Path("../orbit"), home_alias):
        registered = schedules.collect_snapshot(selected, registry, {})
        assert not registered["errors"]
        assert {item["path"]: item["owner"] for item in registered["rows"]} == {
            path: owner for path, (owner, _) in expected.items() if owner != "Unknown"
        }
    unreadable_metadata.add(marker)
    scanned.clear()
    blocked = schedules.collect_snapshot(tmp_path, registry, snapshot)
    assert f"Owner metadata read: {home}" in blocked["errors"]
    assert str(home) not in blocked["owners"]
    assert home / "state" not in scanned
    assert {item["path"] for item in blocked["rows"] if item["stale"]} == home_checks
    assert {item["path"] for item in blocked["rows"] if item["source"].startswith("home check: ")} == set(expected)
    scanned.clear()
    selected_blocked = schedules.collect_snapshot(home_alias, registry, blocked)
    assert home / "state" not in scanned
    assert {item["path"] for item in selected_blocked["rows"] if item["stale"]} == home_checks
    unreadable_metadata.add(registry)
    scanned.clear()
    registry_blocked = schedules.collect_snapshot(home_alias, registry, selected_blocked)
    assert "Owner registry" in registry_blocked["errors"]
    assert home / "state" not in scanned
    assert home_checks <= {item["path"] for item in registry_blocked["rows"] if item["stale"]}
    unreadable_metadata.remove(registry)
    registry_content = registry.read_text()
    registry.write_text(
        f"- nova-mate-b2 - Other owner (home: {other}; scope: Reports; projects: nova; added 2026-10-21)\n"
    )
    scanned.clear()
    unregistered = schedules.collect_snapshot(tmp_path, registry, registry_blocked)
    assert not unregistered["errors"]
    assert home / "state" not in scanned
    assert not home_checks & {item["path"] for item in unregistered["rows"]}
    registry.write_text(registry_content)
    scanned.clear()
    uncached = schedules.collect_snapshot(tmp_path, registry, unregistered)
    assert f"Owner metadata read: {home}" in uncached["errors"]
    assert home / "state" not in scanned
    assert not home_checks & {item["path"] for item in uncached["rows"]}
    unreadable_metadata.clear()
    snapshot = schedules.collect_snapshot(tmp_path, registry, uncached)
    assert not snapshot["errors"]
    assert all(not item["stale"] for item in snapshot["rows"])
    assert home_checks <= {item["path"] for item in snapshot["rows"]}
    unavailable.add(home / "state")
    stale = schedules.collect_snapshot(tmp_path, registry, snapshot)
    assert f"Home checks: {home}" in stale["errors"]
    assert {item["path"] for item in stale["rows"] if item["stale"]} == home_checks
    unavailable.clear()
    recovered = schedules.collect_snapshot(tmp_path, registry, stale)
    assert not recovered["errors"]
    assert all(not item["stale"] for item in recovered["rows"])
    extra.unlink()
    removed = schedules.collect_snapshot(tmp_path, registry, recovered)
    assert str(extra) not in {item["path"] for item in removed["rows"]}
    unreadable_metadata.add(marker)
    blocked = schedules.collect_snapshot(tmp_path, registry, removed)
    assert {item["path"] for item in blocked["rows"] if item["stale"]} == home_checks
    unreadable_metadata.clear()
    marker.write_text("another-mate\n")
    scanned.clear()
    rejected = schedules.collect_snapshot(home_alias, registry, blocked)
    assert f"Owner metadata: {home}" in rejected["errors"]
    assert str(home) not in rejected["owners"]
    assert home / "state" not in scanned
    assert not home_checks & {item["path"] for item in rejected["rows"]}
