import json
import shutil

import pytest
from test_imessage import ROOT, bun

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

RELAY = json.dumps(str(ROOT / "apps/imessage/relay.ts"))
SOURCE = f"""
import {{ relayTarget, relayTargetCurrent }} from {RELAY};
const mate = {{ id: "web-mate", home: "/disposable/web", scope: "Website pages; exclude native applications" }};
const request = {{ requestId: "photon-original", text: "Context: Fix the website menu", authored: "Fix the website menu",
  firstmate: false, mateEligible: true }};
const work = {{ kind: "relay", category: "work", target: mate.id, domains: [mate.id] }};
"""


def test_single_registered_domain_selects_its_mate():
    result = bun(SOURCE + "console.log(JSON.stringify(relayTarget([request], work, [mate]) === mate));")
    assert result is True


@pytest.mark.parametrize("metadata", [
    {"domains": ["web-mate", "data-mate"]},
    {"target": "unknown", "domains": ["unknown"]},
    {"target": "firstmate", "domains": ["firstmate"]},
    {"domains": ["data-mate"]},
    {"domains": []},
    {"domains": None},
    {"category": "approval"},
    {"category": "external"},
    {"category": "orchestration"},
    {"category": "ambiguous"},
    {"category": "social"},
])
def test_unsafe_or_uncertain_metadata_keeps_firstmate(metadata):
    result = bun(SOURCE + f"""
console.log(JSON.stringify(relayTarget([request], {{ ...work, ...{json.dumps(metadata)} }}, [mate]) ?? null));
""")
    assert result is None


@pytest.mark.parametrize("metadata", [None, [], "web-mate", {}, {"target": "web-mate"}])
def test_missing_or_malformed_metadata_keeps_firstmate(metadata):
    result = bun(SOURCE + f"console.log(JSON.stringify(relayTarget([request], {json.dumps(metadata)}, [mate]) ?? null));")
    assert result is None


@pytest.mark.parametrize("restriction", [
    {"firstmate": True},
    {"mateEligible": False},
    {"mateEligible": None},
    {"mutationPath": "/disposable/file"},
    {"authored": "Approve the website release"},
    {"authored": "The website password is private"},
    {"authored": "Delete the website data"},
])
def test_model_metadata_cannot_replace_authenticated_restrictions(restriction):
    result = bun(SOURCE + f"""
const restricted = {{ ...request, ...{json.dumps(restriction)} }};
const metadata = {{ ...work, firstmate: false, mateEligible: true, authored: request.authored }};
console.log(JSON.stringify(relayTarget([restricted], metadata, [mate]) ?? null));
""")
    assert result is None


def test_one_protected_request_keeps_the_whole_burst_with_firstmate():
    result = bun(SOURCE + """
console.log(JSON.stringify(relayTarget([request, { ...request, requestId: "second", authored: "Approve the release" }], work, [mate]) ?? null));
""")
    assert result is None


def test_missing_authored_text_uses_the_original_text_for_protection():
    result = bun(SOURCE + """
const { authored, ...original } = request;
console.log(JSON.stringify(relayTarget([{ ...original, text: "Approve the release" }], work, [mate]) ?? null));
""")
    assert result is None


def test_empty_requests_or_registry_keep_firstmate():
    result = bun(SOURCE + """
console.log(JSON.stringify([relayTarget([], work, [mate]) ?? null, relayTarget([request], work, []) ?? null]));
""")
    assert result == [None, None]


def test_relay_preserves_original_identity_authority_and_registered_home():
    result = bun(SOURCE + """
Object.freeze(request);
const requests = Object.freeze([request]);
const before = JSON.stringify(requests);
const selected = relayTarget(requests, { ...work, requestId: "forged", text: "forged", authored: "forged",
  home: "/forged", scope: "all work" }, [mate]);
console.log(JSON.stringify({ unchanged: JSON.stringify(requests) === before, originalId: request.requestId,
  authored: request.authored, selectedIsRegistered: selected === mate }));
""")
    assert result == {
        "unchanged": True,
        "originalId": "photon-original",
        "authored": "Fix the website menu",
        "selectedIsRegistered": True,
    }


def test_unchanged_registry_passes_the_per_send_check():
    result = bun(SOURCE + "console.log(JSON.stringify(relayTargetCurrent(mate, [{ ...mate }])));")
    assert result is True


@pytest.mark.parametrize("change", [None, {"id": "replacement"}, {"home": "/replacement"}, {"scope": "reports only"}])
def test_removed_or_changed_registry_fails_the_per_send_check(change):
    registry = "[]" if change is None else f"[{{ ...mate, ...{json.dumps(change)} }}]"
    result = bun(SOURCE + f"console.log(JSON.stringify(relayTargetCurrent(mate, {registry})));")
    assert result is False
