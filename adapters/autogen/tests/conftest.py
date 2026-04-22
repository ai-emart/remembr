from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK_PYTHON = ROOT / "sdk" / "python"

for path in (ROOT, SDK_PYTHON):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
