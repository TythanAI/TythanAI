# Roadmap

This is a directional roadmap for **TythanAI Community Edition**, not a commitment.
Priorities may shift based on user feedback.

## Now (Community Edition)

- SAST via Semgrep + a curated rule set (Python / JS / TS / Java / Go / Rust / PHP / Ruby)
- SCA via OSV.dev + EPSS enrichment, with an offline fallback
- Secrets detection in source
- IaC scanner (Terraform, CloudFormation, Kubernetes)
- Web3 auditing — core checks for TON FunC/Tolk, Solidity, Solana/Anchor, CosmWasm
- GitHub Actions integration
- SARIF 2.1.0, JSON and HTML reports

## Next (within 3 months)

- Expanded Community Web3 rule coverage
- Docker image published
- Honest public benchmark on the Juliet corpus
- More example CI integrations

## Pro / Enterprise

Advanced capabilities are available in the commercial editions (for teams and audit firms):

- Full rule library (3,400+) and deep Web3 analysis (symbolic execution, formal checks)
- Full CPG taint analysis (Go / Java / Rust)
- AutoPR auto-generated fix pull requests, AI-powered fix suggestions
- DAST, SBOM compliance (SPDX / CycloneDX)
- SaaS dashboard, webhooks, multi-agent orchestration, GitHub App
- Priority support & SLA

See the comparison table in the [README](README.md#community-vs-pro--enterprise).

## Not planned

- Offensive tooling of any kind
- Features that require persistent code upload without explicit user opt-in
