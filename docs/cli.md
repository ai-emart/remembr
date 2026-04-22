# CLI

The Python SDK ships a `remembr` CLI for quick operator workflows and local debugging.

## Install

--8<-- "_includes/install-python-sdk.md"

## Global flags

```bash
remembr --help
remembr --version
remembr --api-key rk_demo --base-url http://localhost:8000/api/v1 health
```

## Config

```bash
remembr config set api_key rk_demo
remembr config set base_url http://localhost:8000/api/v1
remembr config get api_key
remembr config show
```

## Health

```bash
remembr health
```

## Store

```bash
remembr store "Customer prefers Friday summaries" --session SESSION_ID --role user --tags kind:preference,topic:billing
```

Options:

- `--session`, `-s`
- `--role`, `-r`
- `--tags`, `-t`
- `--json`

## Search

```bash
remembr search "When should we send summaries?" --session SESSION_ID --limit 5
```

Options:

- `--session`, `-s`
- `--limit`, `-n`
- `--json`

## Sessions

```bash
remembr sessions list --limit 20 --offset 0
remembr sessions get SESSION_ID
```

## Export

```bash
remembr export --format json --output remembr_export.json
remembr export --format csv --session SESSION_ID --output remembr_export.csv
```

Options:

- `--output`, `-o`
- `--format`, `-f`
- `--from`
- `--to`
- `--session`, `-s`

