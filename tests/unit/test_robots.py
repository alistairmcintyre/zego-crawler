import pytest

from crawler.fetcher import TextResult
from crawler.robots import AllowAll, RobotsPolicy


class StubGetter:
    def __init__(self, text: str = "", status: int | None = 200):
        self.text = text
        self.status = status
        self.requested: list[str] = []

    async def get_text(self, url: str) -> TextResult:
        self.requested.append(url)
        return TextResult(status=self.status, text=self.text)


async def test_disallowed_paths_are_blocked() -> None:
    getter = StubGetter("User-agent: *\nDisallow: /private/\n")
    policy = RobotsPolicy("my-bot", getter)
    await policy.load("https://example.com")

    assert getter.requested == ["https://example.com/robots.txt"]
    assert policy.allows("https://example.com/public")
    assert not policy.allows("https://example.com/private/x")


async def test_agent_specific_rules_apply() -> None:
    getter = StubGetter("User-agent: my-bot\nDisallow: /\n\nUser-agent: *\nDisallow:\n")
    policy = RobotsPolicy("my-bot", getter)
    await policy.load("https://example.com")
    assert not policy.allows("https://example.com/anything")


async def test_missing_robots_allows_everything() -> None:
    policy = RobotsPolicy("my-bot", StubGetter(status=404))
    await policy.load("https://example.com")
    assert policy.allows("https://example.com/private/x")


@pytest.mark.parametrize("status", [None, 500, 503])
async def test_server_error_or_failed_request_disallows_everything(status: int | None) -> None:
    policy = RobotsPolicy("my-bot", StubGetter(status=status))
    await policy.load("https://example.com")
    assert not policy.allows("https://example.com/")


async def test_reload_clears_disallow_all() -> None:
    getter = StubGetter(status=503)
    policy = RobotsPolicy("my-bot", getter)
    await policy.load("https://example.com")
    getter.status = 404
    await policy.load("https://www.example.com")
    assert policy.allows("https://www.example.com/")


async def test_reloading_for_a_new_host_replaces_the_old_rules() -> None:
    getter = StubGetter("User-agent: *\nDisallow: /\n")
    policy = RobotsPolicy("my-bot", getter)
    await policy.load("https://example.com")
    assert not policy.allows("https://example.com/x")

    getter.status = 404  # the new host has no robots.txt
    await policy.load("https://www.example.com")

    assert getter.requested[-1] == "https://www.example.com/robots.txt"
    assert policy.allows("https://www.example.com/x")


async def test_allow_all() -> None:
    policy = AllowAll()
    await policy.load("https://example.com")
    assert policy.allows("https://example.com/anything")
