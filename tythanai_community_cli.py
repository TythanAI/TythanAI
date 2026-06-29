#!/usr/bin/env python3
# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tythanai_community_cli.py — Community Edition CLI entry point.

Usage:
    python tythanai_community_cli.py scan <target>  [options]
    python tythanai_community_cli.py version

Options:
    --no-sast          Skip SAST (Semgrep + custom rules)
    --no-sca           Skip SCA / dependency CVE scan
    --no-secrets       Skip secrets detection
    --no-iac           Skip IaC scan
    --no-web3          Skip Web3 / smart-contract audit
    --sarif <file>     Write SARIF 2.1.0 output to <file>
    --html  <file>     Write HTML report to <file>
    --json  <file>     Write JSON findings to <file>
    --quiet            Suppress progress messages
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path

# ── Ensure repo root is on the path ──────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from community.gates import PREMIUM_FEATURES, UPGRADE_URL
from community.scanner import CommunityScanner
from community.report import write_sarif, write_html
from community.vex import write_vex
from community.policy import Policy, evaluate

# ─── ANSI colours (graceful fallback on Windows/CI) ──────────────────────────

_NO_COLOR = not sys.stdout.isatty() or os.environ.get("NO_COLOR")

def _c(code: str, text: str) -> str:
    return text if _NO_COLOR else f"\033[{code}m{text}\033[0m"

RED    = lambda t: _c("31", t)
YELLOW = lambda t: _c("33", t)
GREEN  = lambda t: _c("32", t)
CYAN   = lambda t: _c("36", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)
PURPLE = lambda t: _c("35", t)

_SEV_FN = {
    "CRITICAL": RED,
    "HIGH":     lambda t: _c("31;1", t),
    "MEDIUM":   YELLOW,
    "LOW":      CYAN,
    "INFO":     DIM,
}

# ─── Banner ───────────────────────────────────────────────────────────────────

_BANNER = r"""
  ______      __  __               ___    ____
 /_  __/_  __/ /_/ /_  ____ ____  /   |  /  _/
  / / / / / / __/ __ \/ __ `/ _ \/ /| |  / /
 / / / /_/ / /_/ / / / /_/ /  __/ ___ |_/ /
/_/  \__, /\__/_/ /_/\__,_/\___/_/  |_/___/
    /____/   Community Edition  v1.0
"""

def _print_banner() -> None:
    print(PURPLE(_BANNER))
    print(BOLD("  SAST · SCA · Secrets · IaC · TON · Solana · CosmWasm · Solidity"))
    print(DIM("  Free, source-available, no account required — tythanai.io\n"))

# ─── Summary helpers ──────────────────────────────────────────────────────────

_RISK_COLORS = {
    "CRITICAL": RED, "HIGH": lambda t: _c("31;1", t),
    "MEDIUM": YELLOW, "LOW": CYAN, "CLEAN": GREEN,
}

def _print_summary(result) -> None:
    risk = result.risk_level()
    risk_fn = _RISK_COLORS.get(risk, DIM)
    sev = result.by_severity

    print()
    print(BOLD("━" * 60))
    print(BOLD("  SCAN SUMMARY"))
    print(BOLD("━" * 60))
    print(f"  Target    : {result.target}")
    print(f"  Risk      : {risk_fn(BOLD(risk))} ({result.risk_score()}/100)")
    print(f"  Findings  : {BOLD(str(result.total))}")
    print()
    print(f"  {'CRITICAL':10s} {RED(str(sev['CRITICAL'])):>4}")
    print(f"  {'HIGH':10s} {_c('31;1',str(sev['HIGH'])):>4}")
    print(f"  {'MEDIUM':10s} {YELLOW(str(sev['MEDIUM'])):>4}")
    print(f"  {'LOW':10s} {CYAN(str(sev['LOW'])):>4}")
    print(f"  {'INFO':10s} {DIM(str(sev['INFO'])):>4}")
    print()
    print(f"  SAST     : {len(result.sast_findings)} findings")
    print(f"  SCA/CVE  : {len(result.sca_findings)} findings")
    print(f"  Secrets  : {len(result.secrets_findings)} findings")
    print(f"  IaC      : {len(result.iac_findings)} findings")
    print(f"  Web3     : {len(result.web3_findings)} findings")

    if result.errors:
        print()
        print(YELLOW("  Partial scan warnings:"))
        for e in result.errors:
            print(DIM(f"    · {e}"))

    print(BOLD("━" * 60))


def _print_findings(result, quiet: bool) -> None:
    if quiet or not result.all_findings:
        return
    print()
    print(BOLD("  FINDINGS"))
    print()
    for i, f in enumerate(result.all_findings, 1):
        sev = f.get("severity", "INFO").upper()
        fn  = _SEV_FN.get(sev, DIM)
        title = f.get("title", f.get("message", "Finding"))
        file_ = f.get("file", "")
        line  = f.get("line", "")
        src   = f.get("source", "")
        loc   = f"{file_}:{line}" if file_ and line else file_
        print(f"  {DIM(str(i).rjust(3))}  {fn(sev.ljust(8))}  {BOLD(title)}")
        if loc:
            print(f"        {DIM(loc)}")
        rule_id = f.get("rule_id", f.get("id", ""))
        if rule_id:
            print(f"        {DIM(rule_id + '  [' + src + ']')}")
        print()


def _print_gated(result) -> None:
    shown = set()
    lines = []
    for g in result.gated_features:
        if g.feature_key not in shown:
            shown.add(g.feature_key)
            desc = PREMIUM_FEATURES.get(g.feature_key, g.feature_key)
            lines.append(f"  🔒  {desc}")
    if lines:
        print()
        print(BOLD("  PREMIUM FEATURES (not included in Community Edition)"))
        for l in lines:
            print(DIM(l))
        print()
        print(f"  {BOLD('Upgrade:')} {CYAN(UPGRADE_URL)}")
        print()


# ─── Command handlers ─────────────────────────────────────────────────────────

def cmd_scan(args) -> int:
    target = args.target
    if not Path(target).exists():
        print(RED(f"Error: target not found: {target}"), file=sys.stderr)
        return 1

    if not args.quiet:
        _print_banner()
        print(f"  Scanning {BOLD(target)} …\n")

    t0 = time.monotonic()
    scanner = CommunityScanner(target)
    result = scanner.run(
        sast=not args.no_sast,
        sca=not args.no_sca,
        secrets=not args.no_secrets,
        iac=not args.no_iac,
        web3=not args.no_web3,
    )
    elapsed = time.monotonic() - t0

    _print_findings(result, args.quiet)
    _print_summary(result)
    _print_gated(result)

    if not args.quiet:
        print(DIM(f"  Completed in {elapsed:.1f}s"))
        print()

    # ── Output files ──────────────────────────────────────────────────────────
    if args.sarif:
        write_sarif(result, args.sarif)
        if not args.quiet:
            print(f"  SARIF   → {args.sarif}")

    if args.html:
        write_html(result, args.html)
        if not args.quiet:
            print(f"  HTML    → {args.html}")

    if args.json:
        payload = {
            "target": result.target,
            "risk_level": result.risk_level(),
            "risk_score": result.risk_score(),
            "total": result.total,
            "by_severity": result.by_severity,
            "findings": result.all_findings,
        }
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if not args.quiet:
            print(f"  JSON    → {args.json}")

    # Exit code: 0 = clean / info only, 1 = low+, 2 = medium+, 3 = critical/high
    risk = result.risk_level()
    if risk == "CLEAN":      return 0
    if risk == "LOW":        return 1
    if risk == "MEDIUM":     return 2
    return 3


def cmd_version(args) -> int:
    print("TythanAI Community Edition v1.0.0")
    print("Copyright (c) 2026 TythanAI Labs — BSL 1.1")
    print("https://tythanai.io")
    return 0


# ─── CI gate (scan → SARIF + VEX → policy gate, one command) ──────────────────

def _resolve_policy(args, target: str) -> Policy:
    """
    Resolve the gate policy: explicit --policy file, else an auto-discovered
    config in the target/cwd, else the built-in default. CLI flags (--fail-on,
    --max-*) always override whatever the base policy says.
    """
    if args.policy:
        base = Policy.from_file(args.policy)
    else:
        base = Policy.discover(target, os.getcwd()) or Policy.default()

    overrides: dict = {}
    if args.fail_on is not None:
        overrides["fail_on"] = args.fail_on.upper()
    for attr in ("max_critical", "max_high", "max_medium", "max_low", "max_total"):
        val = getattr(args, attr)
        if val is not None:
            overrides[attr] = val
    if args.fail_on_scan_errors:
        overrides["fail_on_scan_errors"] = True

    if overrides:
        # Validate the merged fail_on through from_dict, then keep the rest.
        if "fail_on" in overrides:
            Policy.from_dict({"fail_on": overrides["fail_on"]})
        base = dataclasses.replace(base, **overrides)
    return base


def _print_gate(decision, policy: Policy) -> None:
    print()
    print(BOLD("━" * 60))
    if decision.passed:
        print(BOLD(GREEN("  GATE: PASS")))
    else:
        print(BOLD(RED("  GATE: FAIL")))
    print(BOLD("━" * 60))
    c = decision.counts
    print(f"  Policy    : fail_on={policy.fail_on}"
          + (f", max_total={policy.max_total}" if policy.max_total is not None else ""))
    print(f"  Findings  : {decision.total} considered"
          + (f", {decision.ignored} allowlisted" if decision.ignored else ""))
    print(f"  {RED('CRITICAL')} {c['CRITICAL']}   {_c('31;1','HIGH')} {c['HIGH']}   "
          f"{YELLOW('MEDIUM')} {c['MEDIUM']}   {CYAN('LOW')} {c['LOW']}")
    if decision.reasons:
        print()
        print(YELLOW("  Gate failed because:"))
        for r in decision.reasons:
            print(f"    {RED('✗')} {r}")
    print(BOLD("━" * 60))


def cmd_ci(args) -> int:
    target = args.target
    if not Path(target).exists():
        print(RED(f"Error: target not found: {target}"), file=sys.stderr)
        return 2

    if not args.quiet:
        _print_banner()
        print(f"  CI scan: {BOLD(target)} …\n")

    t0 = time.monotonic()
    scanner = CommunityScanner(target)
    result = scanner.run(
        sast=not args.no_sast,
        sca=not args.no_sca,
        secrets=not args.no_secrets,
        iac=not args.no_iac,
        web3=not args.no_web3,
    )
    elapsed = time.monotonic() - t0

    _print_findings(result, args.quiet)
    _print_summary(result)

    # ── Artifacts: SARIF + VEX by default, JSON/HTML on request ───────────────
    sarif_path = args.sarif or ("tythanai.sarif" if not args.no_artifacts else None)
    vex_path = args.vex or ("tythanai.openvex.json" if not args.no_artifacts else None)

    written: list[str] = []
    if sarif_path:
        write_sarif(result, sarif_path)
        written.append(f"SARIF → {sarif_path}")
    if vex_path:
        doc = write_vex(result, vex_path)
        written.append(f"OpenVEX → {vex_path} ({len(doc['statements'])} statement(s))")
    if args.html:
        write_html(result, args.html)
        written.append(f"HTML  → {args.html}")
    if args.json:
        payload = {
            "target": result.target,
            "risk_level": result.risk_level(),
            "risk_score": result.risk_score(),
            "total": result.total,
            "by_severity": result.by_severity,
            "findings": result.all_findings,
        }
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written.append(f"JSON  → {args.json}")

    if written and not args.quiet:
        print()
        print(BOLD("  ARTIFACTS"))
        for w in written:
            print(f"    {w}")

    # ── Policy gate ───────────────────────────────────────────────────────────
    policy = _resolve_policy(args, target)
    decision = evaluate(result, policy)
    _print_gate(decision, policy)

    if not args.quiet:
        print(DIM(f"  Completed in {elapsed:.1f}s"))
        print()

    if args.exit_zero:
        return 0
    return decision.exit_code


# ─── Argument parser ──────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tythanai-community",
        description="TythanAI Community Edition — Web3-native security scanner",
    )
    sub = p.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="Scan a directory or file")
    scan.add_argument("target", help="Path to scan")
    scan.add_argument("--no-sast",    action="store_true")
    scan.add_argument("--no-sca",     action="store_true")
    scan.add_argument("--no-secrets", action="store_true")
    scan.add_argument("--no-iac",     action="store_true")
    scan.add_argument("--no-web3",    action="store_true")
    scan.add_argument("--sarif", metavar="FILE")
    scan.add_argument("--html",  metavar="FILE")
    scan.add_argument("--json",  metavar="FILE")
    scan.add_argument("--quiet", "-q", action="store_true")

    # ── ci: scan → SARIF + VEX → policy gate, one command for pipelines ───────
    ci = sub.add_parser(
        "ci",
        help="One-shot CI gate: scan, emit SARIF + OpenVEX, enforce a policy",
    )
    ci.add_argument("target", help="Path to scan")
    ci.add_argument("--no-sast",    action="store_true")
    ci.add_argument("--no-sca",     action="store_true")
    ci.add_argument("--no-secrets", action="store_true")
    ci.add_argument("--no-iac",     action="store_true")
    ci.add_argument("--no-web3",    action="store_true")
    ci.add_argument("--sarif", metavar="FILE",
                    help="SARIF output path (default: tythanai.sarif)")
    ci.add_argument("--vex", metavar="FILE",
                    help="OpenVEX output path (default: tythanai.openvex.json)")
    ci.add_argument("--html", metavar="FILE")
    ci.add_argument("--json", metavar="FILE")
    ci.add_argument("--no-artifacts", action="store_true",
                    help="Do not write default SARIF/VEX artifacts")
    ci.add_argument("--policy", metavar="FILE",
                    help="Policy config (.tythanai.yml / .json); auto-discovered if omitted")
    ci.add_argument("--fail-on", metavar="LEVEL", default=None,
                    help="Severity floor that fails the build "
                         "(CRITICAL|HIGH|MEDIUM|LOW|INFO|NONE; default HIGH)")
    ci.add_argument("--max-critical", type=int, default=None, dest="max_critical")
    ci.add_argument("--max-high",     type=int, default=None, dest="max_high")
    ci.add_argument("--max-medium",   type=int, default=None, dest="max_medium")
    ci.add_argument("--max-low",      type=int, default=None, dest="max_low")
    ci.add_argument("--max-total",    type=int, default=None, dest="max_total")
    ci.add_argument("--fail-on-scan-errors", action="store_true",
                    dest="fail_on_scan_errors",
                    help="Fail the gate if any scanner errored (partial scan)")
    ci.add_argument("--exit-zero", action="store_true",
                    help="Always exit 0 (report-only; still writes artifacts)")
    ci.add_argument("--quiet", "-q", action="store_true")

    sub.add_parser("version", help="Show version information")

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "scan":
        sys.exit(cmd_scan(args))
    elif args.command == "ci":
        sys.exit(cmd_ci(args))
    elif args.command == "version":
        sys.exit(cmd_version(args))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
