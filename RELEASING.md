# Releasing Remembr

This document describes how to release a new version of Remembr, including publishing to PyPI and npm.

## GitHub Secrets Setup

Before releasing, you must add the following secrets to the GitHub repository:

### PyPI API Token

1. Go to [PyPI Account Settings](https://pypi.org/manage/account/)
2. Navigate to API tokens section
3. Create a new API token with scope "Project: remembr"
4. Copy the token
5. Go to your GitHub repository Settings → Secrets and variables → Actions
6. Add a new secret named `PYPI_API_TOKEN` with the token value

### NPM Token

1. Go to [npmjs.com](https://www.npmjs.com/) and log in
2. Navigate to your account settings → Access Tokens
3. Create a new Automation token (or use an existing one)
4. Copy the token
5. Go to your GitHub repository Settings → Secrets and variables → Actions
6. Add a new secret named `NPM_TOKEN` with the token value

## Release Process

To release a new version:

1. Update version numbers in:
   - `server/pyproject.toml` (version field)
   - `sdk/python/pyproject.toml` (version field)
   - `sdk/typescript/package.json` (version field)

2. Commit the version changes:
   ```bash
   git add server/pyproject.toml sdk/python/pyproject.toml sdk/typescript/package.json
   git commit -m "Bump version to X.Y.Z"
   ```

3. Create and push a version tag:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```

This will automatically:
- Run the full test suite on Ubuntu, macOS, and Windows
- Publish Python SDK to PyPI (if tests pass)
- Publish TypeScript SDK to npm (if tests pass)
- Create a GitHub Release with auto-generated notes (if tests pass)

## Version Tag Format

Tags must follow semantic versioning: `vX.Y.Z` where:
- X is the major version
- Y is the minor version
- Z is the patch version

Example: `v0.2.0`, `v1.0.0`, `v0.2.1`
