"""Taiga webhook listener — turns Kanban card moves into loop triggers.

There are TWO automated triggers (matching the proposal):

  card moved into "Spec"  ->  generate_spec_stage()   (AI writes the spec, then
                              Slack notifies the developer to review it)
  card moved into "Dev"   ->  agentic_loop()           (the Actor<->Critic loop)

The approval BETWEEN them (human gate #1) is the developer moving the card
Spec -> Dev themselves in Taiga; this listener does not auto-advance it.

Run:
    REPO_DIR=/path/to/clone LOOP_MODE=mock TAIGA_WEBHOOK_SECRET=... \\
        python3 -m connectors.taiga_webhook            # listens on :8099/taiga

Stdlib only (http.server) — no web framework needed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SPEC_COLUMN = os.environ.get("SPEC_COLUMN", "Spec")
DEV_COLUMN = os.environ.get("DEV_COLUMN", "Dev")
LOOP_MODE = os.environ.get("LOOP_MODE", "mock")
REPO_DIR = os.environ.get("REPO_DIR", "")
WEBHOOK_SECRET = os.environ.get("TAIGA_WEBHOOK_SECRET", "")


def verify_signature(secret: str, payload: bytes, signature: str) -> bool:
    """Taiga signs the raw body with HMAC-SHA1 (hex) using the project secret."""
    if not secret:
        return True  # dev only; set a secret in production
    expected = hmac.new(secret.encode(), payload, hashlib.sha1).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def moved_into(event: dict) -> str | None:
    """Return the column the card just moved INTO, or None if not a card move."""
    if event.get("type") not in ("userstory", "task"):
        return None
    if event.get("action") != "change":
        return None
    status_change = (event.get("change", {}).get("diff", {}) or {}).get("status")
    if not status_change:
        return None
    return status_change.get("to")


def requirement_from_event(event: dict) -> str:
    data = event.get("data", {})
    subject = data.get("subject", "").strip()
    description = (data.get("description") or "").strip()
    return f"{subject}\n\n{description}".strip()


def card_ref_from_event(event: dict):
    return event.get("data", {}).get("ref", "?")


def dispatch(event: dict) -> str:
    """Route a card move to the right stage. Returns a short status string."""
    column = moved_into(event)
    if column not in (SPEC_COLUMN, DEV_COLUMN):
        return "ignored"
    card_ref = card_ref_from_event(event)

    def _go():
        import orchestrator  # lazy import so the listener loads without loop deps
        if column == SPEC_COLUMN:
            print(f"[taiga] card #{card_ref} -> {SPEC_COLUMN}: generating spec")
            orchestrator.generate_spec_stage(
                requirement_from_event(event), Path(REPO_DIR),
                mode=LOOP_MODE, card_ref=card_ref)
        else:  # DEV_COLUMN
            print(f"[taiga] card #{card_ref} -> {DEV_COLUMN}: starting Agentic Loop")
            result = orchestrator.agentic_loop(
                Path(REPO_DIR), mode=LOOP_MODE, card_ref=card_ref)
            print(f"[taiga] loop finished: {json.dumps(result, ensure_ascii=False)}")

    threading.Thread(target=_go, daemon=True).start()
    return f"triggered:{column}"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.rstrip("/") != "/taiga":
            self.send_response(404); self.end_headers(); return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not verify_signature(WEBHOOK_SECRET, body,
                                self.headers.get("X-TAIGA-WEBHOOK-SIGNATURE", "")):
            self.send_response(401); self.end_headers()
            self.wfile.write(b"bad signature"); return
        try:
            event = json.loads(body or b"{}")
        except json.JSONDecodeError:
            self.send_response(400); self.end_headers(); return

        status = dispatch(event)
        self.send_response(202 if status.startswith("triggered") else 200)
        self.end_headers()
        self.wfile.write(status.encode())

    def do_GET(self):
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def log_message(self, *_):
        pass


def main():
    port = int(os.environ.get("PORT", "8099"))
    print(f"[taiga] listening on :{port}/taiga  "
          f"triggers: ->{SPEC_COLUMN}=spec, ->{DEV_COLUMN}=loop  mode={LOOP_MODE}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
