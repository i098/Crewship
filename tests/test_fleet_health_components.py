import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import provisions  # noqa: E402


def test_fleet_health_lists_every_provisioned_component():
    listed = set(re.findall(r'(?:name: |github\(|npm\(|plugin\()"([^"]+)"', (ROOT / "tools/fleet-health/components.ts").read_text()))
    expected = (
        set(provisions.GITHUB_LATEST) - {"sentrux-grammars"}  # shares sentrux's release
        | set(provisions.NPM_LATEST)
        | set(provisions.OMP_PLUGINS)
    )
    assert not expected - listed
