import hashlib
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "schedules", Path(__file__).parents[1] / "blueprint/maintenance/crewship-schedules.py"
)
schedules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedules)


def test_mixed_sources_preserve_identity_history_and_owner(tmp_path):
    home = tmp_path / "orbit"
    home.mkdir()
    marker = home / ".fm-secondmate-home"
    marker.write_text("orbit-mate-a1\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/secondmates.md").write_text(
        f"- orbit-mate-a1 - Report owner (home: {home}; scope: Reports; projects: orbit; added 2026-10-21)\n"
    )
    owners, errors = schedules.read_registry(tmp_path / "data/secondmates.md")
    assert not errors
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
    timer, empty, running, success = schedules.properties(
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
        "ExecStart={ path=/srv/orbit/bin/report ; argv[]=/srv/orbit/bin/report ; }\n".replace("/srv/orbit", str(home))
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
    failed = dict(completed, name="broken", result="exit-code (1)", next="2026-10-23 09:00:00 UTC")
    earlier = dict(completed, name="earlier", next="2026-10-22 07:00:00 UTC")
    ordered = sorted([completed, earlier, failed], key=schedules.row_order)
    assert [item["name"] for item in ordered] == ["broken", "earlier", "report"]
    assert schedules.text("report\x1b[31m\n\u202e") == r"report\x1b[31m\n\u202e"
    (tmp_path / "state").mkdir()
    check = tmp_path / "state/report.check.sh"
    check.write_text("#!/bin/sh\n# Check the report\nexit 17\n")
    check.chmod(0o700)
    trust = tmp_path / "state/report.check-trust"
    trust.write_text("fm-custom-check-v1\n" + hashlib.sha256(check.read_bytes()).hexdigest() + "\n")
    trust.chmod(0o600)
    (tmp_path / "state/pull-request.check.sh").write_text("not a registered custom check")
    inventory = schedules.Inventory(tmp_path)
    inventory.owners = {str(tmp_path): "orbit-mate-a1"}
    inventory.refresh_checks()
    checks = [item for items in inventory.saved.values() for item in items]
    assert [item["name"] for item in checks] == ["report.check.sh"]
    assert (checks[0]["owner"], checks[0]["result"]) == ("orbit-mate-a1", "Unknown")
    marker.write_text("another-mate\n")
    owners, errors = schedules.read_registry(tmp_path / "data/secondmates.md")
    assert str(home) not in owners and f"Owner metadata: {home}" in errors
