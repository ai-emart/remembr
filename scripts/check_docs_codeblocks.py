from __future__ import annotations

import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
FENCE_RE = re.compile(r"```python(?:[ \t]+[^\n`]*)?\n(.*?)\n```", re.DOTALL)


def main() -> int:
    failed = False
    for path in TARGETS:
        text = path.read_text(encoding="utf-8")
        for index, match in enumerate(FENCE_RE.finditer(text), start=1):
            code = match.group(1)
            try:
                compile(code, str(path), "exec")
            except SyntaxError as exc:
                failed = True
                print(
                    f"{path}:{index}: syntax error in python fence: {exc.msg} (line {exc.lineno})",
                    file=sys.stderr,
                )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
