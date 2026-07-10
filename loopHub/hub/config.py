"""Load config.toml + repos.toml; secrets from env."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


@dataclass
class RepoEntry:
    name: str
    url: str
    base: str


@dataclass
class Team:
    name: str
    taiga_project: int
    repos: dict[str, RepoEntry]


@dataclass
class Config:
    taiga_base_url: str
    status_names: dict[str, str]        # role -> display name
    port: int
    queue_db_path: str
    webhook_secret: str
    taiga_token: str
    teams: dict[str, Team] = field(default_factory=dict)
    slack_users: dict[str, str] = field(default_factory=dict)   # taiga username -> Slack ID

    def team_for_project(self, project_id: int) -> Team | None:
        for t in self.teams.values():
            if t.taiga_project == project_id:
                return t
        return None


def load(config_path: Path | None = None, repos_path: Path | None = None) -> Config:
    cfg = tomllib.loads((config_path or HERE / "config.toml").read_text())
    repos = tomllib.loads((repos_path or HERE / "repos.toml").read_text())

    teams: dict[str, Team] = {}
    for tname, tdata in repos.get("teams", {}).items():
        entries = {
            rname: RepoEntry(rname, rdata["url"], rdata.get("base", "main"))
            for rname, rdata in tdata.get("repos", {}).items()
        }
        teams[tname] = Team(tname, int(tdata["taiga_project"]), entries)

    return Config(
        taiga_base_url=cfg["taiga"]["base_url"],
        status_names=dict(cfg["statuses"]),
        port=int(cfg["server"]["port"]),
        queue_db_path=cfg["queue"]["db_path"],
        webhook_secret=os.environ.get("LOOPHUB_WEBHOOK_SECRET", ""),
        taiga_token=_resolve_token(cfg["taiga"]["base_url"]),
        teams=teams,
        slack_users=dict(cfg.get("slack_users", {})),
    )


def _resolve_token(base_url: str) -> str:
    """Prefer minting a fresh token from LOOPHUB_TAIGA_USER/PASSWORD — auth
    tokens expire, credentials don't. Falls back to a static token."""
    user = os.environ.get("LOOPHUB_TAIGA_USER", "")
    password = os.environ.get("LOOPHUB_TAIGA_PASSWORD", "")
    if user and password:
        from .taiga import auth_token
        return auth_token(base_url, user, password)
    return os.environ.get("LOOPHUB_TAIGA_TOKEN", "")
