"""Local development server that also works on Windows.

    uv run python -m app.dev            # http://127.0.0.1:8000/docs
    $env:PORT=8001; uv run python -m app.dev   # if 8000 is taken (e.g. by the Docker api)

(Inside Docker we run plain `uvicorn app.main:app`.) Auto-reload is not used
here because uvicorn's reloader would start a child process with Windows'
default event loop, which psycopg's async mode can't use.
"""

import os

import uvicorn

from app.utils.event_loop import run


async def _serve() -> None:
    port = int(os.environ.get("PORT", "8000"))
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="info")
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    run(_serve())
