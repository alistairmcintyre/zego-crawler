"""robots.txt support."""

from __future__ import annotations

import logging
from typing import Protocol
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)


class TextGetter(Protocol):
    async def get_text(self, url: str) -> str | None: ...


class RobotsPolicy:
    """Answers "may we fetch this URL?" according to the site's robots.txt.

    A missing or unreachable robots.txt means everything is allowed, which is the
    conventional interpretation.
    """

    def __init__(self, user_agent: str):
        self._user_agent = user_agent
        self._parser: RobotFileParser | None = None

    async def load(self, origin: str, getter: TextGetter) -> None:
        text = await getter.get_text(f"{origin}/robots.txt")
        if text is None:
            logger.info("No robots.txt found at %s; all URLs allowed", origin)
            return
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        self._parser = parser

    def allows(self, url: str) -> bool:
        return self._parser is None or self._parser.can_fetch(self._user_agent, url)


class AllowAll:
    """Policy used when robots.txt is explicitly ignored."""

    def allows(self, url: str) -> bool:
        return True
