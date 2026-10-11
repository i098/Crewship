import importlib.util
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "pr_preview", Path(__file__).parents[1] / "skills/public/pr-preview/pr_preview.py"
)
pr_preview = importlib.util.module_from_spec(SPEC)
# The public-skill privacy scan reads every file in the skill folder: leave no .pyc there.
sys.dont_write_bytecode = True
SPEC.loader.exec_module(pr_preview)
PATCH = """diff --git a/old name.txt b/new name.txt
similarity index 90%
rename from old name.txt
rename to new name.txt
index 111..222 100644
--- a/old name.txt
+++ b/new name.txt
@@ -8,4 +8,4 @@ def f():
 keep
-gone <b>
+came & went
 tail
\\ No newline at end of file
diff --git a/img.png b/img.png
new file mode 100644
Binary files /dev/null and b/img.png differ
"""


def test_diff_keeps_line_numbers_names_and_escapes_code():
    renamed, binary = pr_preview.split_patch(PATCH)
    assert (renamed["old"], renamed["name"], renamed["status"]) == (
        "old name.txt",
        "new name.txt",
        "renamed",
    )
    assert binary["status"] == "added" and binary["binary"]
    assert pr_preview.count(renamed["patch"]) == (1, 1)
    table = pr_preview.diff_table(renamed, limit=100)
    # Context line 8/8, deleted line 9 has no new number, added line 9 has no old number.
    assert '<tr><td class="n">8</td><td class="n">8</td>' in table
    assert '<tr class="del"><td class="n">9</td><td class="n"></td>' in table
    assert '<tr class="add"><td class="n"></td><td class="n">9</td>' in table
    assert "gone &lt;b&gt;" in table and "came &amp; went" in table
    assert "Binary file not shown" in pr_preview.diff_table(binary, limit=100)
    # One square per change up to five, then proportional; always five squares.
    assert pr_preview.squares(1, 1).count("<i") == 5
    assert pr_preview.squares(4, 21) == '<i class="g"></i>' * 0 + '<i class="r"></i>' * 4 + '<i class="n"></i>'
