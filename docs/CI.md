# CI gate — `tythanai ci`

`tythanai ci` is the one-command entry point for pipelines. It runs a scan,
writes the standard artifacts, evaluates a policy, and sets the process exit
code so a build can be blocked deterministically.

```
scan  →  SARIF (2.1.0)  →  OpenVEX (0.2.0)  →  policy gate  →  exit code
```

Nothing here talks to the network for the gate itself: the same scan result
and the same policy always produce the same verdict.

---

## Quick start

```bash
tythanai ci .                       # default policy: fail on CRITICAL or HIGH
tythanai ci . --fail-on CRITICAL    # only block on CRITICAL
tythanai ci . --exit-zero           # report-only (artifacts still written)
```

On success the gate prints `GATE: PASS` and exits `0`. On a violation it prints
`GATE: FAIL`, lists **every** reason, and exits `1`. A missing target exits `2`.

---

## Artifacts

| File (default) | Format | Use |
|---|---|---|
| `tythanai.sarif` | SARIF 2.1.0 | GitHub Code Scanning, IDE annotations |
| `tythanai.openvex.json` | OpenVEX 0.2.0 | Grype/Trivy filtering, SBOM tooling |

Override the paths with `--sarif FILE` / `--vex FILE`, add `--json FILE` or
`--html FILE`, or disable the defaults with `--no-artifacts`. You can also skip
scanners with `--no-sast`, `--no-sca`, `--no-secrets`, `--no-iac`, `--no-web3`.

### What goes into the VEX document

OpenVEX describes the exploitability status of **known vulnerabilities**
(CVE / GHSA / OSV). Only findings that carry such an identifier — your
vulnerable dependencies (SCA) — become VEX statements. SAST, secrets and IaC
findings are **not** vulnerabilities and are intentionally left out of VEX;
they live in the SARIF report instead.

Every statement is emitted with status `affected`: the scanner observed a
vulnerable component *version* in a manifest. TythanAI does **not** assert
`not_affected` or `fixed` — that requires per-application reachability/triage
this edition does not perform, so a clean status is never fabricated. Each
product is named by a [Package-URL](https://github.com/package-url/purl-spec)
(`pkg:pypi/...`, `pkg:npm/...`, …); when the ecosystem can't be determined the
purl falls back to `pkg:generic` rather than guessing.

The document `@id` is content-addressed (a hash of its statements), so an
unchanged set of findings yields a byte-stable document across runs — handy for
diffing VEX in version control.

---

## Policy

The gate has two complementary controls:

- **`fail_on`** — a severity floor. Any finding at or above this severity fails
  the gate. Default `HIGH` (blocks `CRITICAL` and `HIGH`). Use `NONE` to switch
  the severity floor off entirely.
- **`max_*` budgets** — explicit caps per severity and overall. `None` (the
  default) means unbounded.

### Config file

Drop a `.tythanai.yml` (or `.yaml` / `.json`) at the repo root and it is
auto-discovered:

```yaml
fail_on: HIGH            # CRITICAL | HIGH | MEDIUM | LOW | INFO | NONE
max_critical: 0          # at most N CRITICAL findings (omit for unbounded)
max_high: 5
max_medium: null
max_low: null
max_total: 100           # overall budget across all severities
fail_on_scan_errors: false   # also fail if a scanner errored (partial scan)
ignore_ids:              # accept findings you have triaged
  - CVE-2020-14343
  - PY001
ignore_sources:          # accept whole categories by source prefix
  - secrets
```

Keys may also be nested under a top-level `gate:` or `policy:` section.

Allowlisted findings (`ignore_ids` / `ignore_sources`) are removed **before**
any threshold is applied, so an accepted finding never trips the gate — but it
is still counted and reported as `ignored` for transparency.

### Command-line overrides

CLI flags always win over the config file:

| Flag | Effect |
|---|---|
| `--policy FILE` | Use a specific policy file instead of auto-discovery |
| `--fail-on LEVEL` | Severity floor (`CRITICAL`…`INFO`, or `NONE`) |
| `--max-critical N` / `--max-high` / `--max-medium` / `--max-low` | Per-severity budgets |
| `--max-total N` | Overall budget |
| `--fail-on-scan-errors` | Fail if any scanner errored |
| `--exit-zero` | Always exit `0` (report-only) |

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Gate passed (or `--exit-zero`) |
| `1` | Gate failed — policy violated |
| `2` | Bad invocation (e.g. target path does not exist) |

---

## GitHub Actions

```yaml
name: Security Scan
on: [push, pull_request]
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install tythanai-community
      - run: tythanai ci . --sarif results.sarif
      - if: always()                 # upload findings even when the gate fails
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: results.sarif
```

Use `if: always()` on the upload step so Code Scanning still receives the SARIF
when the gate blocks the build.
