import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validation_postmortem", ROOT / "scripts/validation_postmortem.py"
)
postmortem = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(postmortem)


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "validation-postmortems.md"
    path.write_text("# Existing log\n", encoding="utf-8")
    monkeypatch.setattr(postmortem, "LOG", path)
    return path


def arguments(**changes):
    values = dict(run="run-42", step="CI", **{"root-cause": "race"},
                  fix="wait for completion", prevention="tests/test_race.py")
    values.update(changes)
    return [item for key, value in values.items() for item in (f"--{key}", value)]


def test_append_keeps_history_and_one_table_row_per_failure(log):
    before = datetime.now(UTC).date().isoformat()
    postmortem.main(arguments(step=" first | second\nstep "))
    postmortem.main(arguments(run="run-43"))
    after = datetime.now(UTC).date().isoformat()
    lines = log.read_text().splitlines()
    assert lines[0] == "# Existing log"
    assert len(lines) == 3
    assert lines[1].split(" | ")[0] in {f"| {before}", f"| {after}"}
    assert lines[1].endswith(
        " | run-42 | first &#124; second step | race | wait for completion | tests/test_race.py |"
    )
    assert lines[2].endswith(
        " | run-43 | CI | race | wait for completion | tests/test_race.py |"
    )



@pytest.mark.parametrize("existing", ["", "# No final newline", "# Final newline\n"])
def test_append_starts_a_new_row(log, existing):
    log.write_text(existing)
    postmortem.main(arguments())
    result = log.read_text()
    prefix = existing + ("\n" if existing and not existing.endswith("\n") else "")
    assert result.startswith(prefix + "| ")
    assert result.count("\n") == prefix.count("\n") + 1

@pytest.mark.parametrize("field", postmortem.FIELDS)
@pytest.mark.parametrize("value", ["", " \n\t "])
def test_empty_field_never_changes_log(log, field, value):
    with pytest.raises(SystemExit) as error:
        postmortem.main(arguments(**{field: value}))
    assert error.value.code == 2
    assert log.read_text() == "# Existing log\n"


@pytest.mark.parametrize("field", postmortem.FIELDS)
def test_missing_field_never_changes_log(log, field):
    args = arguments()
    index = args.index(f"--{field}")
    del args[index:index + 2]
    with pytest.raises(SystemExit) as error:
        postmortem.main(args)
    assert error.value.code == 2
    assert log.read_text() == "# Existing log\n"


def test_seed_records_have_all_six_columns():
    rows = [line for line in (ROOT / "docs/validation-postmortems.md").read_text().splitlines()
            if line.startswith("| ")][2:]
    assert len(rows) >= 2
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == 6
        assert all(cells)
        assert datetime.strptime(cells[0], "%Y-%m-%d")
        assert cells[1].startswith("https://github.com/")
        assert "https://" in cells[5] or "../" in cells[5]
