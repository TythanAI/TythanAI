# Roadmap

This is a directional roadmap, not a commitment. Priorities may shift based on user feedback.

## Now (current release)

- SAST via Semgrep + custom rule engine (3 462 rules, Python/JS/Go/Java/Rust/Swift/Solidity/FunC)
- SCA via OSV.dev + EPSS enrichment
- Secrets detection (git history + live scan)
- IaC scanner (Terraform, CloudFormation, Kubernetes)
- Container scanner (Dockerfile, docker-compose)
- Web3 auditors: TON FunC/Tolk, Solidity, Solana/Anchor, CosmWasm
- Multi-language CPG (taint analysis) for Python, JavaScript, Go, Java, Rust
- AutoPR: auto-generated fix pull requests
- DAST (passive, requires ZAP)
- SBOM generation (SPDX 2.3, CycloneDX 1.4)
- GitHub Actions integration
- SARIF 2.1.0 output
- SaaS onboarding, webhooks, usage dashboard

## Next (within 3 months)

- PyPI package + Docker image published
- VS Code extension published to marketplace
- Honest public benchmark on full Juliet 1.3 corpus (multi-language)
- GitHub App (install once, auto-scans all repos)
- Slack and Jira integrations
- Self-hosted Helm chart

## Later

- Kotlin, Scala, Move, Rust WASM contract auditors
- IDE plugin for JetBrains
- SOC 2 Type II audit
- Managed cloud scanning (no local install required)

## Not planned

- Offensive tooling of any kind
- Features that require persistent code upload without explicit user opt-in
