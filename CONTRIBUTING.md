# Contributing to miniMDM

Thank you for your interest in contributing. This document explains how the project works and what is expected from contributors and maintainers.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to report a bug](#how-to-report-a-bug)
- [How to suggest a feature](#how-to-suggest-a-feature)
- [How to submit a pull request](#how-to-submit-a-pull-request)
- [Pull request requirements](#pull-request-requirements)
- [Code style](#code-style)
- [Setting up a development environment](#setting-up-a-development-environment)
- [Running tests](#running-tests)
- [Review process](#review-process)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating you agree to abide by its terms.

---

## How to report a bug

1. Search [existing issues](../../issues) first — the bug may already be reported.
2. If not, open a new issue using the **Bug report** template.
3. Include as much detail as possible: steps to reproduce, expected behaviour, actual behaviour, and your environment (OS, Python version, PostgreSQL version).

Security vulnerabilities should **not** be reported as public issues. Please contact the maintainer directly.

---

## How to suggest a feature

1. Search [existing issues](../../issues) to see if it has already been discussed.
2. Open a new issue using the **Feature request** template.
3. Describe the problem you are trying to solve, not just the solution. This helps the maintainer understand the use case and suggest the best approach.
4. Wait for the maintainer to acknowledge the issue before investing time in an implementation. This avoids wasted work if the direction is not right for the project.

---

## How to submit a pull request

### For small, obvious bug fixes
You may open a PR directly without an issue.

### For everything else
1. Open an issue first and get acknowledgement from the maintainer.
2. Fork the repository and create a branch from `main`:
   ```bash
   git checkout -b fix/short-description   # bug fix
   git checkout -b feat/short-description  # new feature
   ```
3. Make your changes. Keep the scope focused — one logical change per PR.
4. Ensure all requirements in the checklist below are met.
5. Open the pull request against `main`. Opening a **draft PR** early is encouraged — it signals that work is in progress and allows early feedback.
6. Mark the PR as ready for review when complete.

---

## Pull request requirements

Every PR must satisfy all of the following before it will be merged:

- **Tests pass** — run `uv run pytest` and confirm all tests pass. Integration tests require `TEST_DATABASE_URL` (see [Running tests](#running-tests)).
- **New behaviour is tested** — new features and bug fixes must include appropriate tests.
- **Docs updated** — if the API or config format changes, update `docs/reference.md`. If user-facing features change, update `README.md` as needed.
- **Changelog entry** — add a line under `[Unreleased]` in `Changelog.md` in the appropriate section (`Added`, `Fixed`, `Security`, or `Changed`).
- **Focused scope** — do not bundle unrelated refactoring, style fixes, or extra features in the same PR.
- **Linter passes** — run `uv run ruff check app tests` and resolve any issues.

---

## Code style

### Python

- Follow [PEP 8](https://peps.python.org/pep-0008/) conventions.
- Use `snake_case` for functions, variables, and module names.
- Maximum line length: **100 characters**.
- Imports in three groups, each alphabetically sorted: standard library → third-party → local (`app.*`).
- Docstrings only where the logic is not self-evident. Do not add docstrings to every function.
- Type hints are welcome but not required on every function.
- Use [SQLAlchemy Core](https://docs.sqlalchemy.org/en/20/core/) expressions for database queries — avoid raw SQL strings and the ORM.

The project uses [ruff](https://docs.astral.sh/ruff/) for linting. Run it before submitting:

```bash
uv run ruff check app tests
```

### JavaScript

- ES6+ syntax: `const`/`let`, arrow functions, `async`/`await`, template literals.
- `camelCase` for functions and variables.
- No framework — vanilla DOM APIs only.
- No external dependencies may be added to the frontend.

---

## Setting up a development environment

Requirements: Python 3.11+, PostgreSQL 14+, [uv](https://docs.astral.sh/uv/).

```bash
git clone <repository-url>
cd minimdm

# Install dependencies (including dev dependencies)
uv sync

# Copy and configure environment variables
cp .env.example .env
# Edit .env — set DATABASE_URL to your local PostgreSQL instance

# Copy and edit the config file
cp config/minimdm.example.yaml config/minimdm.yaml

# Start the development server
uv run uvicorn app.main:app --reload
```

---

## Running tests

Unit tests (no database required):

```bash
uv run pytest tests/test_schema_loader.py tests/test_table_manager.py tests/test_templates.py
```

Integration tests (require a PostgreSQL test database):

```bash
export TEST_DATABASE_URL="postgresql://user:pass@localhost:5432/minimdm_test"
uv run pytest
```

The integration tests create and drop a `test` schema on each run. The test database must exist but can otherwise be empty.

---

## Review process

- The maintainer will review PRs when available. There is no guaranteed response time.
- Review feedback will be left as comments on the PR. Please address all comments before requesting a re-review.
- Once approved, the maintainer will **squash merge** the PR into `main`. Your PR commits will be collapsed into a single commit — this keeps the `main` history clean and readable.
- If a PR has been open for a long time without activity it may be closed. It can always be reopened.
