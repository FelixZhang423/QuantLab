from __future__ import annotations

import ssl
import sys
from pathlib import Path

import certifi


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_original_create_default_context = ssl.create_default_context


def _create_certifi_context(
    purpose: ssl.Purpose = ssl.Purpose.SERVER_AUTH,
    *,
    cafile: str | None = None,
    capath: str | None = None,
    cadata: str | bytes | None = None,
) -> ssl.SSLContext:
    if cafile is None and capath is None and cadata is None:
        cafile = certifi.where()
    return _original_create_default_context(
        purpose=purpose,
        cafile=cafile,
        capath=capath,
        cadata=cadata,
    )


ssl.create_default_context = _create_certifi_context

from streamlit.web import cli as streamlit_cli  # noqa: E402


def main() -> None:
    app_path = Path(__file__).with_name("streamlit_app.py")
    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.headless",
        "true",
        *sys.argv[1:],
    ]
    streamlit_cli.main()


if __name__ == "__main__":
    main()
