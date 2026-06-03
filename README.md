# TythanAI — Community Edition

**Open-source security scanner with native Web3 auditing for TON, Solana, CosmWasm and Solidity — alongside SAST, SCA, secrets and IaC. One CLI. No account. No telemetry.**

[![PyPI](https://img.shields.io/pypi/v/tythanai-community?color=brightgreen)](https://pypi.org/project/tythanai-community/)
[![License: BSL 1.1](https://img.shields.io/badge/License-BSL%201.1-orange.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-blueviolet.svg)](CONTRIBUTING.md)

---

```bash
pip install tythanai-community
tythanai scan ./your-project
```

That's it. No sign-up, no API key, no data leaves your machine.

---

## See it in action

Point it at a folder and it tells you what's actually exploitable *(example output)*:

```
  ______      __  __               ___    ____
 /_  __/_  __/ /_/ /_  ____ ____  /   |  /  _/
  / / / / / / __/ __ \/ __ `/ _ \/ /| |  / /
 / / / /_/ / /_/ / / / /_/ /  __/ ___ |_/ /
/_/  \__, /\__/_/ /_/\__,_/\___/_/  |_/___/
    /____/   Community Edition  v1.0

  Scanning ./your-project …

  FINDINGS

    1  CRITICAL  AWS secret exposed in source code
        app.py:3
        SEC-AWS_ACCESS_KEY  [secret_detector]

    2  CRITICAL  Potential reentrancy: state written after external call
        Vault.sol:6
        SC-SOL-001  [web3]

    3  HIGH      Low-level .call() return value not checked — silent failure
        Vault.sol:6
        SOL005  [solidity_scanner]

  SCAN SUMMARY
  Risk      : CRITICAL (95/100)
  Findings  : 5    (CRITICAL 3 · HIGH 2)
```

---

## What's included in Community Edition

Everything below runs locally, free, with no account:

- 🪙 **Web3 auditing** — core security checks for **TON FunC/Tolk**, **Solidity/EVM**, **Solana/Anchor** and **CosmWasm** (reentrancy, signer checks, replay, unchecked calls, access control…)
- 🔍 **SAST** — Semgrep + a curated rule set across common languages (Python, JS/TS, Java, Go, Rust, PHP, Ruby)
- 📦 **SCA** — dependency CVEs via OSV.dev with EPSS exploit-probability ranking, plus an offline fallback
- 🔑 **Secrets** — API keys, tokens and private keys detected in your source
- ☁️ **IaC** — Terraform, Kubernetes and CloudFormation misconfigurations
- 📄 **Reports** — SARIF 2.1.0 (GitHub Code Scanning), JSON and HTML
- 🔒 **Private by design** — fully local, no account, no telemetry

> Community Edition is a fast, practical scanner that catches the most common, highest-impact issues. Deeper analysis (full rule library, symbolic/formal Web3 analysis, auto-fix PRs, CI integrations) lives in **Pro / Enterprise** — see the table below.

---

## Usage

```bash
# Scan everything
tythanai scan ./myproject

# Only the checks you want
tythanai scan ./myproject --no-sast --no-sca   # e.g. secrets + IaC + web3 only

# Machine-readable output
tythanai scan ./myproject --sarif results.sarif   # upload to GitHub Code Scanning
tythanai scan ./myproject --json  report.json
tythanai scan ./myproject --html  report.html

# Quiet mode (findings + summary only, no banner)
tythanai scan ./myproject --quiet
```

Exit code is non-zero when findings are present, so it drops straight into CI.

### GitHub Actions

```yaml
name: Security Scan
on: [push, pull_request]
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install tythanai-community
      - run: tythanai scan . --sarif results.sarif
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: results.sarif
```

---

## Community vs Pro / Enterprise

Community Edition is genuinely useful on its own. Teams shipping production smart contracts — and audit firms — upgrade for depth, automation and support.

| Capability | Community (free) | Pro / Enterprise |
|---|:--:|:--:|
| TON / Solidity / Solana / CosmWasm auditing | Core checks | **Full rule set + deep analysis** |
| Web3 symbolic execution & formal checks | — | ✓ |
| SAST rule library | up to 500 rules | **3,400+ rules** |
| Full CPG taint analysis (Go / Java / Rust) | — | ✓ |
| SCA (OSV.dev + EPSS) | ✓ | ✓ |
| Secrets & IaC | ✓ | ✓ |
| AutoPR — auto-generated fix pull requests | — | ✓ |
| AI-powered fix suggestions | — | ✓ |
| DAST (active web scanning) | — | ✓ |
| SBOM compliance (SPDX / CycloneDX) | — | ✓ |
| SaaS dashboard, webhooks, multi-agent orchestration | — | ✓ |
| Priority support & SLA | — | ✓ |
| Reports | SARIF · JSON · HTML | + SBOM · compliance |

**Need Pro or Enterprise?** TythanAI Pro is built for teams and audit firms running TON / Solana / Solidity engagements. To request access or a demo, [open an issue](https://github.com/TythanAI/TythanAI/issues/new) or visit [tythanai.io](https://tythanai.io).

---

## How Community Edition compares

| | TythanAI CE | Semgrep OSS | Slither | Snyk |
|---|:--:|:--:|:--:|:--:|
| SAST | ✓ | ✓ | ✗ | partial |
| SCA (OSV.dev) | ✓ | ✗ | ✗ | ✓ |
| Secrets | ✓ | partial | ✗ | ✓ |
| Solidity / EVM | ✓ | ✗ | ✓ | ✗ |
| **TON FunC / Tolk** | ✓ | ✗ | ✗ | ✗ |
| **Solana / Anchor** | ✓ | ✗ | ✗ | ✗ |
| **CosmWasm** | ✓ | ✗ | ✗ | ✗ |
| SARIF output | ✓ | partial | ✗ | partial |
| No account required | ✓ | ✓ | ✓ | ✗ |

---

## Requirements

- Python 3.10+
- Optional: [Semgrep](https://semgrep.dev) (`pip install semgrep`) for the full SAST rule set

---

## Contributing

Issues, rules and chain auditors are very welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Found a security bug? See [SECURITY.md](SECURITY.md).

If TythanAI saved you from shipping a vulnerability, a ⭐ helps other people find it.

---

## License

[Business Source License 1.1](LICENSE) — source-available, free for non-production and evaluation use; converts to Apache 2.0 on 2029-06-01.
