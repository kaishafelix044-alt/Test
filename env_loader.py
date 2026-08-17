"""Tiny stdlib .env loader (no external dependency).

Real process environment variables always win over the file, so container/CI
settings override .env. Handles quoted values (straight and the curly quotes a
word processor may insert) and `KEY=VALUE` with '=' inside the value.
"""

from __future__ import annotations

import os
from pathlib import Path

# opening quote -> closing quote (ascii + the curly quotes a word processor inserts)
_CLOSE = {'"': '"', "'": "'", "“": "”", "”": "”",
          "‘": "’", "’": "’"}


def _parse_value(val: str) -> str:
    val = val.strip()
    if not val:
        return ""
    if val[0] in _CLOSE:  # quoted: take up to the matching close quote, ignore trailing comment
        close = _CLOSE[val[0]]
        end = val.find(close, 1)
        return val[1:end] if end != -1 else val[1:]
    # unquoted: strip an inline comment (space/tab before '#'), then surrounding space
    for marker in (" #", "\t#"):
        i = val.find(marker)
        if i != -1:
            val = val[:i]
    return val.strip()


def load_dotenv(path: str | Path = ".env", override: bool = False) -> int:
    p = Path(path)
    if not p.is_file():
        return 0
    loaded = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key.lower().startswith("export "):
            key = key[7:].strip()
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = _parse_value(val)
            loaded += 1
    return loaded
