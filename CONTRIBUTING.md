# Contributing to TythanAI Community Edition

Thanks for your interest in contributing! This guide covers how to set up your
development environment, run the tests, and submit pull requests.

---

## Development setup

### Prerequisites

- Python 3.10 or later
- Git
- (Optional) [Semgrep](https://semgrep.dev) for the full SAST rule set

### Clone and install

```bash
git clone https://github.com/TythanAI/TythanAI.git
cd TythanAI

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows

# Install in editable mode with dev tools
pip install -e ".[dev]"
```

### Verify

```bash
tythanai version
tythanai scan .
```

---

## Running tests

```bash
pytest tests/ -v
```

The community test suite lives in `tests/test_community_edition.py` and covers
the CLI, the scan pipeline, gating, and report output.

---

## Project layout

```
tythanai_community_cli.py   # CLI entry point
community/                  # scan orchestrator, feature gates, report writers
  scanner.py               #   the free-tier scan pipeline
  gates.py                 #   Community vs Pro feature gating + limits
  report.py                #   SARIF / HTML / JSON output
scanners/                  # SAST, SCA, secrets, Solidity scanners
blockchain/                # TON + multi-chain (Solana/CosmWasm) auditors
backend/scanners/          # IaC scanner
tests/                     # test suite
```

## Where to contribute

- **Improve a scanner** — the detectors live in `scanners/` and `blockchain/`.
- **Reduce false positives** — adjust detection logic and add a regression test.
- **Improve reports** — `community/report.py` (SARIF / HTML / JSON).
- **Docs & examples** — README, CI examples, usage guides.

When you change detection behaviour, add a test fixture (a small vulnerable and a
small clean sample) so we can confirm both detection and the absence of false
positives.

---

## Code style

TythanAI uses **ruff** for linting and formatting (configured in `pyproject.toml`):

```bash
ruff format .
ruff check . --fix
```

All new code should use Python type hints.

---

## Pull requests

Before opening a PR:

- [ ] `pytest tests/ -v` passes
- [ ] `ruff check .` is clean
- [ ] New behaviour has at least one positive and one negative test
- [ ] The PR description explains **what** changed and **why**

Use conventional-commit titles, e.g.:

```
feat(ton): add bounce-handling check
fix(secrets): reduce false positives on base64 blobs
docs: clarify SARIF upload example
```

A clean, squash-merged history is preferred, and all CI checks must be green.

---

## Getting help

- Open a GitHub Issue for bugs or feature requests (check existing issues first).
- For security vulnerabilities, **do not** open a public issue — see [SECURITY.md](SECURITY.md).

> Looking for advanced capabilities (full rule library, deep Web3 analysis,
> AutoPR, SaaS/CI integrations)? Those are part of TythanAI Pro / Enterprise —
> see the comparison in the [README](README.md#community-vs-pro--enterprise).
