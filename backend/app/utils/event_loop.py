"""Event-loop helper.

psycopg 3 async mode cannot run on Windows' default ProactorEventLoop, so on
Windows we explicitly use a SelectorEventLoop. On Linux (Docker) nothing changes.
"""

import asyncio
import selectors
import sys
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def loop_factory() -> asyncio.AbstractEventLoop:
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop()


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro, loop_factory=loop_factory)
