# Debugging With Memory Diff

`/memory/diff` is useful when you want to inspect what changed between two runs without replaying the entire history.

## Use cases

- Compare before and after an agent review cycle
- See what a failing run wrote before it crashed
- Audit what a background worker added overnight

## Example

```python
from datetime import datetime, timedelta, timezone

from remembr import RemembrClient


def build_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=1), now
```

Use the API directly for diff workflows today, then search or export the matching sessions for deeper inspection.

