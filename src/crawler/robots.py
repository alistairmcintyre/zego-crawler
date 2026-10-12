"""robots.txt support."""

from __future__ import annotations

import logging
from typing import Protocol
from urllib.robotparser import RobotFileParser

from crawler.fetcher import TextResult

logger = logging.getLogger(__name__)


class TextGetter(Protocol):
    async def get_text(self, url: str) -> TextResult: ...


class RobotsPolicy:
    """Answers "may we fetch this URL?" according to the site's robots.txt.

    Follows RFC 9309: a missing robots.txt (4xx) allows everything, but a server
    error or failed request disallows everything, since the site may be struggling
    or its rules may be unknown. ``load`` can be called again if the crawl moves
    to a different host.
    """

    def __init__(self, user_agent: str, getter: TextGetter):
        self._user_agent = user_agent
        self._getter = getter
        self._parser: RobotFileParser | None = None
        self._disallow_all = False

    async def load(self, origin: str) -> None:
        self._parser = None
        self._disallow_all = False
        url = f"{origin}/robots.txt"
        result = await self._getter.get_text(url)
        if result.status is None or result.status >= 500:
            logger.warning(
                "Could not fetch %s (%s); treating every URL as disallowed. "
                "Use --ignore-robots to crawl anyway.",
                url,
                result.status or "request failed",
            )
            self._disallow_all = True
        elif 200 <= result.status < 300:
            parser = RobotFileParser()
            parser.parse(result.text.splitlines())
            self._parser = parser
        else:
            logger.info("No robots.txt at %s (HTTP %d); all URLs allowed", url, result.status)

    def allows(self, url: str) -> bool:
        if self._disallow_all:
            return False
        return self._parser is None or self._parser.can_fetch(self._user_agent, url)


class AllowAll:
    """Policy used when robots.txt is explicitly ignored."""

    async def load(self, origin: str) -> None:
        pass

    def allows(self, url: str) -> bool:
        return True
