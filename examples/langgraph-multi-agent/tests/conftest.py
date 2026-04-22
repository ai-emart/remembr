from __future__ import annotations

import sys
from pathlib import Path

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXAMPLE_ROOT.parents[1]
SDK_ROOT = REPO_ROOT / "sdk" / "python"

for path in (EXAMPLE_ROOT, REPO_ROOT, SDK_ROOT):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)
