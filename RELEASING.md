# Releasing

Releases are automated from Git tags.

## Normal Release Flow

1. Make sure `main` is green.
2. Update package versions and changelog entries as needed.
3. Create and push the tag:

```bash
git tag v0.2.0
git push origin v0.2.0
```

Pushing a tag that matches `v*.*.*` triggers `.github/workflows/release.yml`, which:

- runs the server, SDK, adapter, lint, and docs checks
- publishes `sdk/python` to PyPI
- publishes `sdk/typescript` to npm
- creates a GitHub Release with generated release notes

## Required GitHub Secrets

Add these secrets in the GitHub repository before the first release:

### `PYPI_API_TOKEN`

1. Open the repository on GitHub.
2. Go to `Settings`.
3. In the left sidebar, open `Secrets and variables` -> `Actions`.
4. Click `New repository secret`.
5. Set `Name` to `PYPI_API_TOKEN`.
6. Paste your PyPI API token as the value.
7. Click `Add secret`.

To create the token in PyPI:

1. Sign in to PyPI.
2. Open `Account settings`.
3. Open `API tokens`.
4. Create a token with permission to publish the `remembr` project.
5. Copy it immediately and store it as the GitHub secret above.

### `NPM_TOKEN`

1. Open the repository on GitHub.
2. Go to `Settings`.
3. In the left sidebar, open `Secrets and variables` -> `Actions`.
4. Click `New repository secret`.
5. Set `Name` to `NPM_TOKEN`.
6. Paste your npm access token as the value.
7. Click `Add secret`.

To create the token in npm:

1. Sign in to npm.
2. Open `Access Tokens`.
3. Create a publish-capable token for the `@remembr/sdk` package.
4. Copy it immediately and store it as the GitHub secret above.

## Optional Repo Settings

To enforce "PR cannot be merged if any job fails", enable branch protection for `main`
and require the CI status checks from `.github/workflows/ci.yml`.
