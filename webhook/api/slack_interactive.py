"""
Vercel Serverless Function — Slack 인터랙티브 버튼 핸들러

버튼 클릭 흐름:
  Slack → POST /api/slack_interactive
       → 서명 검증
       → GitHub Actions workflow_dispatch 트리거 (acm_ids 전달)
       → run.py --stage 2 --execute --acm-ids <ids>
"""
from http.server import BaseHTTPRequestHandler
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError


# ── Slack 서명 검증 ──────────────────────────────────────────────────────────

def _verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    if not secret:
        return False
    if abs(time.time() - float(timestamp)) > 300:   # 5분 이상 된 요청 거부
        return False
    base = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── GitHub Actions workflow_dispatch 트리거 ──────────────────────────────────

def _trigger_github_actions(acm_ids: str, workflow: str, inputs: dict) -> tuple[bool, str]:
    token = os.environ.get("GH_PAT", "")
    owner = os.environ.get("GH_OWNER", "sungjun818")
    repo  = os.environ.get("GH_REPO",  "")
    if not token or not repo:
        return False, "GH_PAT 또는 GH_REPO 환경변수 없음"

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    payload = json.dumps({"ref": "master", "inputs": inputs}).encode()

    req = urllib.request.Request(url, data=payload, headers={
        "Authorization":        f"Bearer {token}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type":         "application/json",
    })

    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status == 204, "성공"
    except HTTPError as e:
        body = e.read().decode()
        return False, f"GitHub API 오류 {e.code}: {body}"


def _trigger_upsell(acm_ids: str, test_mode: bool = False) -> tuple[bool, str]:
    return _trigger_github_actions(acm_ids, "weekly_upsell.yml", {
        "stage":     "2",
        "execute":   "true",
        "acm_ids":   acm_ids,
        "test_mode": "true" if test_mode else "false",
    })


def _trigger_monthly_report(acm_ids: str, test_mode: bool = False) -> tuple[bool, str]:
    return _trigger_github_actions(acm_ids, "monthly_report.yml", {
        "execute":   "true",
        "acm_ids":   acm_ids,
        "test_mode": "true" if test_mode else "false",
    })


# ── Slack 즉시 응답 ──────────────────────────────────────────────────────────

def _slack_ack(acm_ids: str, action_id: str) -> dict:
    if action_id == "send_all_upsell":
        count = len(acm_ids.split(","))
        msg = f"✅ *{count}개 숙소* 이메일 발송을 시작합니다. 잠시 후 완료 알림이 옵니다."
    else:
        msg = f"📧 이메일 발송을 시작합니다. (acm_id: {acm_ids})"
    return {"text": msg, "response_type": "in_channel"}


# ── Vercel Handler ───────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        length  = int(self.headers.get("Content-Length", 0))
        body    = self.rfile.read(length)
        ts      = self.headers.get("X-Slack-Request-Timestamp", "")
        sig     = self.headers.get("X-Slack-Signature", "")

        # 서명 검증
        if not _verify_slack_signature(body, ts, sig):
            self._respond(401, {"error": "invalid signature"})
            return

        # payload 파싱 (Slack은 URL-encoded form으로 전송)
        form    = urllib.parse.parse_qs(body.decode("utf-8"))
        payload = json.loads(form.get("payload", ["{}"])[0])

        ptype   = payload.get("type", "")

        # Slack URL 검증 (앱 등록 시 한 번만 발생)
        if ptype == "url_verification":
            self._respond(200, {"challenge": payload.get("challenge")})
            return

        if ptype != "block_actions":
            self._respond(200, {"ok": True})
            return

        actions   = payload.get("actions", [])
        if not actions:
            self._respond(200, {"ok": True})
            return

        action    = actions[0]
        action_id = action.get("action_id", "")
        acm_ids   = action.get("value", "")

        # ── 업셀 테스트 발송 ──────────────────────────────────────────────
        if action_id == "test_upsell_email":
            self._respond(200, {"text": f"🔍 테스트 이메일 발송 중... (acm_id: {acm_ids})", "response_type": "in_channel"})
            ok, msg = _trigger_upsell(acm_ids, test_mode=True)
            print(f"[{'INFO' if ok else 'ERROR'}] 업셀 테스트 트리거: {msg}")
            return

        # ── 월간 리포트 테스트 발송 ───────────────────────────────────────
        if action_id == "test_monthly_report":
            self._respond(200, {"text": f"🔍 월간 리포트 테스트 발송 중... (acm_id: {acm_ids})", "response_type": "in_channel"})
            ok, msg = _trigger_monthly_report(acm_ids, test_mode=True)
            print(f"[{'INFO' if ok else 'ERROR'}] 월간 리포트 테스트 트리거: {msg}")
            return

        # ── 월간 리포트 실제 발송 ─────────────────────────────────────────
        if action_id in ("send_monthly_report", "send_all_monthly_report") and acm_ids:
            self._respond(200, {"text": f"📊 월간 리포트 발송 시작 (acm_ids: {acm_ids})", "response_type": "in_channel"})
            ok, msg = _trigger_monthly_report(acm_ids)
            print(f"[{'INFO' if ok else 'ERROR'}] 월간 리포트 트리거: {msg}")
            return

        # ── 업셀 실제 발송 ────────────────────────────────────────────────
        if action_id not in ("send_upsell_email", "send_all_upsell") or not acm_ids:
            self._respond(200, {"ok": True})
            return

        ack = _slack_ack(acm_ids, action_id)
        self._respond(200, ack)

        ok, msg = _trigger_upsell(acm_ids)
        if not ok:
            print(f"[ERROR] 업셀 트리거 실패: {msg}")
        else:
            print(f"[INFO] 업셀 트리거 성공: acm_ids={acm_ids}")

    def do_GET(self):
        self._respond(200, {"status": "ok", "service": "upsell-webhook"})

    def _respond(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass  # Vercel 로그로 대체
