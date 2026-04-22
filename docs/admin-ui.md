# Admin UI

The local admin UI is mounted at `/admin` in non-production environments.

## What it is for

- Browsing sessions
- Inspecting stored episodes
- Reviewing memory state during local development

## Start it

```bash
bash scripts/docker-init.sh
```

Then open `http://localhost:8000/admin`.

## Good uses

- Debugging tag shapes
- Confirming soft-deleted episodes disappear from normal views
- Verifying checkpoint-heavy workflows created the expected sessions

## Caution

Treat the admin UI as an operator tool. Do not expose it publicly without your own access control layer.
