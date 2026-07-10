import hub.slack as slack


def test_notify_is_noop_without_config(monkeypatch):
    monkeypatch.delenv("LOOPHUB_SLACK_TOKEN", raising=False)
    monkeypatch.delenv("LOOPHUB_SLACK_CHANNEL", raising=False)
    calls = []
    monkeypatch.setattr(slack.httpx, "post", lambda *a, **k: calls.append(a))
    slack.notify("hello")
    assert calls == []


def test_notify_posts_when_configured(monkeypatch):
    monkeypatch.setenv("LOOPHUB_SLACK_TOKEN", "xoxb-test")
    monkeypatch.setenv("LOOPHUB_SLACK_CHANNEL", "C123")
    sent = {}

    class FakeResp:
        def json(self):
            return {"ok": True}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers, json=json)
        return FakeResp()

    monkeypatch.setattr(slack.httpx, "post", fake_post)
    story = {"ref": 40, "subject": "Dashboard sign-out link",
             "project_extra_info": {"slug": "angular-frontend"}}
    slack.spec_ready("http://localhost:9000", story, "admin", 1)
    assert sent["json"]["channel"] == "C123"
    assert "#40" in sent["json"]["text"] and "待審查" in sent["json"]["text"]
    assert "project/angular-frontend/us/40" in sent["json"]["text"]


def test_notify_failure_never_raises(monkeypatch):
    monkeypatch.setenv("LOOPHUB_SLACK_TOKEN", "xoxb-test")
    monkeypatch.setenv("LOOPHUB_SLACK_CHANNEL", "C123")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(slack.httpx, "post", boom)
    slack.notify("hello")   # must not raise
