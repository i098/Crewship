"""The Instagram DM webhook (docs/imessage.md#cards): apps/imessage/instagram-webhook.ts.

The payloads are Meta's shapes with made-up ids; the inbox command is a shell stand-in that records its arguments.
"""

import hashlib
import hmac
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

HOOK = json.dumps(str(Path(__file__).parents[1] / "apps/imessage/instagram-webhook.ts"))
SECRET = "test-app-secret"
OPERATOR = "17841400000000001"
ACCOUNT = "17841400000000099"
NOTE = "[Instagram DM from 17841400000000001; answer with fm-insta-reply] "
REEL_URL = "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=18000000000000001&signature=abc"

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


def dm(mid, sender=OPERATOR, **message):
    return {"object": "instagram", "entry": [{"id": ACCOUNT, "time": 1761287294500, "messaging": [
        {"sender": {"id": sender}, "recipient": {"id": ACCOUNT}, "timestamp": 1761287294123, "message": {"mid": mid, **message}},
    ]}]}


def post(payload, signature="good"):
    body = json.dumps(payload)
    header = {"good": "sha256=" + hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest(), "bad": "sha256=" + "0" * 64}.get(signature)
    return {"method": "POST", "body": body, "headers": {"X-Hub-Signature-256": header} if header else {}}


def run(tmp_path, *requests, notify_exit=0):
    """Send `requests` to one webhook handler; return the answers, the `say` lines, the log rows and the notes."""
    calls = tmp_path / "calls"
    stub = tmp_path / "notify"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"{calls}\"\nexit {notify_exit}\n")
    stub.chmod(0o755)
    log = tmp_path / "ig" / "messages.jsonl"
    code = textwrap.dedent(f"""
        import {{ instagramWebhook }} from {HOOK};
        const said = [];
        const hook = instagramWebhook({{ appSecret: {json.dumps(SECRET)}, verifyToken: "verify-me", operator: {json.dumps(OPERATOR)},
          log: {json.dumps(str(log))}, notify: [{json.dumps(str(stub))}], say: (l) => said.push(l) }});
        const answers = [];
        for (const r of {json.dumps(list(requests))}) {{
          const res = await hook(new Request("http://127.0.0.1/instagram/webhook" + (r.query ?? ""), r));
          answers.push([res.status, await res.text()]);
        }}
        console.log(JSON.stringify({{ answers, said }}));
    """)
    result = subprocess.run(["bun", "-e", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    out["rows"] = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    out["calls"] = calls.read_text().splitlines() if calls.exists() else []
    return out


def test_the_verification_handshake_needs_the_verify_token(tmp_path):
    query = "?hub.mode=subscribe&hub.challenge=1158201444&hub.verify_token="
    out = run(tmp_path, {"method": "GET", "query": query + "verify-me"}, {"method": "GET", "query": query + "wrong"})
    assert out["answers"] == [[200, "1158201444"], [403, "forbidden\n"]]


def test_unsigned_or_badly_signed_posts_file_nothing(tmp_path):
    out = run(tmp_path, post(dm("m1", text="hi"), None), post(dm("m1", text="hi"), "bad"))
    assert [a[0] for a in out["answers"]] == [403, 403]
    assert out["rows"] == [] and out["calls"] == []


def test_a_text_dm_files_one_note_then_one_row(tmp_path):
    out = run(tmp_path, post(dm("aWdfZAG1faXRlbTox", text="  hi  ")))
    assert out["answers"] == [[200, "EVENT_RECEIVED"]]
    assert out["calls"] == [f"--request-id ig-aWdfZAG1faXRlbTox -- {NOTE}hi"]
    assert out["rows"] == [{"at": 1761287294, "id": "aWdfZAG1faXRlbTox", "thread": OPERATOR, "sender": OPERATOR, "type": "text", "text": "  hi  "}]


def test_a_reel_share_carries_its_url_media_id_and_caption(tmp_path):
    reel = {"type": "ig_reel", "payload": {"reel_video_id": "18000000000000001", "title": "Sunset\n over  the bay", "url": REEL_URL}}
    post_share = [{"type": "share", "payload": {"url": "https://www.instagram.com/p/C0abc/"}},
                  {"type": "ig_post", "payload": {"ig_post_media_id": "18000000000000002", "title": "a post", "url": REEL_URL}}]
    out = run(tmp_path, post(dm("m-reel", attachments=[reel])), post(dm("m-post", attachments=post_share)))
    assert out["rows"][0] | {"at": 0} == {"at": 0, "id": "m-reel", "thread": OPERATOR, "sender": OPERATOR, "type": "ig_reel", "url": REEL_URL,
                                          "meta": {"caption": "Sunset over the bay", "media_id": "18000000000000001"}}
    assert out["calls"][0] == f'--request-id ig-m-reel -- {NOTE}{REEL_URL} (media 18000000000000001) caption: "Sunset over the bay"'
    assert out["rows"][1]["type"] == "share" and out["rows"][1]["url"] == "https://www.instagram.com/p/C0abc/"  # the first one wins


def test_a_retried_mid_is_filed_once_also_after_a_restart(tmp_path):
    out = run(tmp_path, post(dm("m1", text="hi")), post(dm("m1", text="hi")))
    again = run(tmp_path, post(dm("m1", text="hi")))
    assert [a[0] for a in out["answers"] + again["answers"]] == [200, 200, 200]
    assert len(again["rows"]) == 1 and len(again["calls"]) == 1


def test_a_dm_from_anyone_else_is_ignored_and_names_the_sender(tmp_path):
    out = run(tmp_path, post(dm("m1", sender="17841400000000777", text="hey")))
    assert out["answers"] == [[200, "EVENT_RECEIVED"]] and out["rows"] == [] and out["calls"] == []
    assert out["said"] == ["instagram webhook: ignored a DM from 17841400000000777 (not INSTAGRAM_DM_OPERATOR)"]


def test_a_refused_note_answers_500_and_files_no_row(tmp_path):
    out = run(tmp_path, post(dm("m1", text="hi")), notify_exit=1)
    assert out["answers"] == [[500, "inbox refused the note\n"]] and out["rows"] == [] and len(out["calls"]) == 1
