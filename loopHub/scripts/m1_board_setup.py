"""M1 board setup: 3 projects, 5+Done columns, required `repo` custom attr,
webhook per project → host.docker.internal:8400, loop-bot membership.

Usage:
    TAIGA_ADMIN_PASSWORD=... LOOPHUB_WEBHOOK_SECRET=... \
        uv run python scripts/m1_board_setup.py

Idempotent: safe to re-run; existing objects are reused.
Prints the taiga_project ids to paste into repos.toml.
"""
import os
import sys

import httpx

BASE = os.environ.get("TAIGA_BASE", "http://localhost:9000")
WEBHOOK_URL = "http://host.docker.internal:8400/webhooks/taiga"
COLUMNS = ["Backlog", "Spec Drafting", "Spec Review", "Dev", "PR-Done", "Done"]
PROJECTS = {          # slug-ish name -> team key in repos.toml
    "payments-board": "payments",
    "lending-board": "lending",
    "cards-board": "cards",
}


def login(username: str, password: str) -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth",
                   json={"type": "normal", "username": username, "password": password})
    r.raise_for_status()
    return r.json()


def main() -> None:
    admin_pw = os.environ["TAIGA_ADMIN_PASSWORD"]
    secret = os.environ["LOOPHUB_WEBHOOK_SECRET"]
    admin = login("admin", admin_pw)
    c = httpx.Client(base_url=BASE,
                     headers={"Authorization": f"Bearer {admin['auth_token']}"},
                     timeout=30)

    existing = {p["name"]: p for p in c.get("/api/v1/projects",
                                            params={"member": admin["id"]}).json()}
    team_ids = {}
    for name, team in PROJECTS.items():
        if name in existing:
            proj = existing[name]
            print(f"project {name} exists (id {proj['id']})")
        else:
            r = c.post("/api/v1/projects", json={
                "name": name, "description": f"{team} team board",
                "creation_template": 1, "is_private": True,
            })
            r.raise_for_status()
            proj = r.json()
            print(f"created project {name} (id {proj['id']})")
        pid = proj["id"]
        team_ids[team] = pid

        # --- columns: ensure the six statuses exist with the right names/order
        statuses = c.get("/api/v1/userstory-statuses", params={"project": pid}).json()
        by_name = {s["name"]: s for s in statuses}
        for i, col in enumerate(COLUMNS):
            if col in by_name:
                continue
            # rename a leftover default if any remain, else create
            leftovers = [s for s in statuses
                         if s["name"] not in COLUMNS and s["name"] not in by_name.values()]
            r = c.post("/api/v1/userstory-statuses", json={
                "project": pid, "name": col, "order": i,
                "is_closed": col == "Done",
            })
            r.raise_for_status()
            by_name[col] = r.json()
            print(f"  + column {col} (id {by_name[col]['id']})")
        # delete default columns not in our list (move stories to Backlog if any)
        for s in statuses:
            if s["name"] not in COLUMNS:
                c.delete(f"/api/v1/userstory-statuses/{s['id']}",
                         params={"moveTo": by_name["Backlog"]["id"]})
                print(f"  - removed default column {s['name']}")
        # fix order + Done closes
        for i, col in enumerate(COLUMNS):
            c.patch(f"/api/v1/userstory-statuses/{by_name[col]['id']}",
                    json={"order": i, "is_closed": col == "Done"})

        # --- required custom attribute `repo`
        attrs = c.get("/api/v1/userstory-custom-attributes",
                      params={"project": pid}).json()
        if not any(a["name"] == "repo" for a in attrs):
            r = c.post("/api/v1/userstory-custom-attributes", json={
                "project": pid, "name": "repo",
                "description": "target repository (must be registered in repos.toml)",
                "type": "text", "order": 1,
            })
            r.raise_for_status()
            print(f"  + custom attribute repo (id {r.json()['id']})")

        # --- webhook
        hooks = c.get("/api/v1/webhooks", params={"project": pid}).json()
        if not any(h["url"] == WEBHOOK_URL for h in hooks):
            r = c.post("/api/v1/webhooks", json={
                "project": pid, "name": "loop-hub",
                "url": WEBHOOK_URL, "key": secret,
            })
            r.raise_for_status()
            print(f"  + webhook -> {WEBHOOK_URL}")

    print("\nrepos.toml project ids:")
    for team, pid in team_ids.items():
        print(f"  [teams.{team}] taiga_project = {pid}")


if __name__ == "__main__":
    sys.exit(main())
