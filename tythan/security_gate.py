# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tythan/security_gate.py — scan AI-authored changes before they reach disk.

This is the feature that makes tythan different from a generic coding
agent: every write_file/edit_file the model proposes is scanned, and only
findings on lines the change *introduces* are reported — pre-existing
issues in the file never block an unrelated edit (run `security_scan` or
`tythanai scan` for those).

The rule set is a compact, dependency-free distillation of the TythanAI
scanners: leaked secrets, dangerous code patterns, insecure config.
"""
from __future__ import annotations

import difflib
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from tythan.tools import _SKIP_DIRS


@dataclass
class Finding:
    rule_id: str
    severity: str        # CRITICAL / HIGH / MEDIUM / LOW
    title: str
    file: str
    line: int            # 1-based
    snippet: str

    def format(self) -> str:
        return f"[{self.severity}] {self.title}  ({self.file}:{self.line})  {self.rule_id}"


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    severity: str
    title: str
    pattern: re.Pattern
    # Only apply to files whose name matches one of these globs; empty = all.
    filenames: tuple[str, ...] = ()


def _r(rule_id: str, severity: str, title: str, pattern: str,
       filenames: tuple[str, ...] = (), flags: int = 0) -> _Rule:
    return _Rule(rule_id, severity, title, re.compile(pattern, flags), filenames)


_PY = ("*.py",)
_JS = ("*.js", "*.jsx", "*.ts", "*.tsx", "*.mjs", "*.cjs")

RULES: list[_Rule] = [
    # ── Secrets ──────────────────────────────────────────────────────────
    _r("SEC-AWS-KEY", "CRITICAL", "AWS access key ID in source",
       r"\b(A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}\b"),
    _r("SEC-PRIVATE-KEY", "CRITICAL", "Private key material in source",
       r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    _r("SEC-GITHUB-TOKEN", "CRITICAL", "GitHub token in source",
       r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"),
    _r("SEC-SLACK-TOKEN", "CRITICAL", "Slack token in source",
       r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    _r("SEC-OPENAI-KEY", "CRITICAL", "OpenAI API key in source",
       r"\bsk-[A-Za-z0-9_-]{20}T3BlbkFJ[A-Za-z0-9_-]{20}\b|\bsk-proj-[A-Za-z0-9_-]{40,}\b"),
    _r("SEC-ANTHROPIC-KEY", "CRITICAL", "Anthropic API key in source",
       r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    _r("SEC-GENERIC-SECRET", "HIGH", "Hardcoded secret/password/token assignment",
       r"""(?i)\b(?:api[_-]?key|secret|passwd|password|auth[_-]?token|access[_-]?token)\b"""
       r"""\s*[:=]\s*["'][^"'\s]{8,}["']"""),

    # ── Dangerous code: Python ───────────────────────────────────────────
    _r("PY-EVAL", "HIGH", "eval()/exec() on dynamic data",
       r"\b(?:eval|exec)\s*\(\s*(?!['\"])", _PY),
    _r("PY-PICKLE", "HIGH", "pickle.loads on untrusted data enables code execution",
       r"\bpickle\.loads?\s*\(", _PY),
    _r("PY-YAML-LOAD", "HIGH", "yaml.load without SafeLoader",
       r"\byaml\.load\s*\((?![^)]*(?:SafeLoader|safe_load))(?![^)]*Loader\s*=\s*yaml\.SafeLoader)", _PY),
    _r("PY-SHELL-TRUE", "HIGH", "subprocess with shell=True — command injection risk",
       r"\bshell\s*=\s*True\b", _PY),
    _r("PY-OS-SYSTEM-FMT", "HIGH", "os.system with interpolated string — command injection risk",
       r"""\bos\.system\s*\(\s*(?:f["']|["'][^"']*["']\s*%|["'][^"']*["']\s*\.\s*format)""", _PY),
    _r("PY-SQL-FSTRING", "CRITICAL", "SQL built with f-string/format — SQL injection risk",
       r"""(?is)\b(?:execute|executemany)\s*\(\s*f["'][^"']*\b(?:select|insert|update|delete)\b[^"']*\{""",
       _PY),
    _r("PY-VERIFY-FALSE", "HIGH", "TLS certificate verification disabled",
       r"\bverify\s*=\s*False\b", _PY),
    _r("PY-UNVERIFIED-CTX", "HIGH", "ssl._create_unverified_context disables TLS verification",
       r"\bssl\._create_unverified_context\b", _PY),
    _r("PY-WEAK-HASH", "MEDIUM", "MD5/SHA1 used for password or token hashing",
       r"\bhashlib\.(?:md5|sha1)\s*\(", _PY),
    _r("PY-RANDOM-TOKEN", "MEDIUM", "random module used for a secret/token — use `secrets`",
       r"(?i)(?:token|secret|password|nonce)\w*\s*=\s*.*\brandom\.(?:random|randint|choice|choices|randrange|getrandbits)\b",
       _PY),

    # ── Dangerous code: JS/TS ────────────────────────────────────────────
    _r("JS-EVAL", "HIGH", "eval()/new Function() on dynamic data",
       r"\beval\s*\(\s*(?!['\"])|\bnew\s+Function\s*\(", _JS),
    _r("JS-CHILD-EXEC", "HIGH", "child_process exec with template literal — command injection risk",
       r"\b(?:exec|execSync)\s*\(\s*`[^`]*\$\{", _JS),
    _r("JS-INNERHTML", "MEDIUM", "innerHTML assignment from dynamic data — XSS risk",
       r"\.innerHTML\s*=\s*(?!['\"`]\s*['\"`])(?!['\"])", _JS),
    _r("JS-DANGEROUSLY", "MEDIUM", "dangerouslySetInnerHTML — XSS risk",
       r"\bdangerouslySetInnerHTML\b", _JS),
    _r("JS-SQL-TEMPLATE", "CRITICAL", "SQL built with template literal interpolation — SQL injection risk",
       r"(?is)\b(?:query|execute)\s*\(\s*`[^`]*\b(?:select|insert|update|delete)\b[^`]*\$\{", _JS),

    # ── Insecure config ──────────────────────────────────────────────────
    _r("CFG-CORS-WILDCARD", "MEDIUM", "CORS allows any origin",
       r"""(?i)(?:Access-Control-Allow-Origin[^\n]{0,40}[:=]\s*["']\*["']|allow_origins\s*=\s*\[\s*["']\*["'])"""),
    _r("CFG-JWT-NONE", "CRITICAL", "JWT 'none' algorithm accepted",
       r"""(?i)\balgorithms?\b[^\n]{0,20}["']none["']"""),
    _r("CFG-BIND-ALL", "LOW", "service bound to 0.0.0.0 (all interfaces)",
       r"""["']0\.0\.0\.0["']"""),
    _r("CFG-DEBUG-TRUE", "LOW", "debug mode enabled",
       r"(?i)\bdebug\s*[:=]\s*True\b"),
]

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

# Filenames whose whole purpose is holding examples/tests of bad patterns.
_IGNORED_NAME_HINTS = (".min.js", ".lock")

_B64_RX = re.compile(r"""["']([A-Za-z0-9+/=_-]{32,})["']""")
_ENTROPY_ASSIGN_RX = re.compile(
    r"""(?i)\b\w*(?:key|secret|token|password|passwd|credential)\w*\s*[:=]\s*["']([A-Za-z0-9+/=_-]{24,})["']"""
)


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in freq.values())


def _matches_filename(rule: _Rule, filename: str) -> bool:
    if not rule.filenames:
        return True
    import fnmatch
    base = os.path.basename(filename)
    return any(fnmatch.fnmatch(base, pat) for pat in rule.filenames)


def scan_content(content: str, filename: str) -> list[Finding]:
    """Scan text as if it were the given file. Returns findings sorted by severity."""
    base = os.path.basename(filename)
    if any(base.endswith(h) for h in _IGNORED_NAME_HINTS):
        return []
    findings: list[Finding] = []
    lines = content.splitlines()
    applicable = [r for r in RULES if _matches_filename(r, filename)]
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        for rule in applicable:
            if rule.pattern.search(line):
                findings.append(Finding(
                    rule.rule_id, rule.severity, rule.title,
                    filename, lineno, stripped[:160],
                ))
        # High-entropy secret assignment (catches keys no regex knows about)
        m = _ENTROPY_ASSIGN_RX.search(line)
        if m and _entropy(m.group(1)) >= 4.0:
            if not any(f.line == lineno and f.rule_id.startswith("SEC-") for f in findings):
                findings.append(Finding(
                    "SEC-HIGH-ENTROPY", "HIGH",
                    "High-entropy value assigned to a credential-named variable",
                    filename, lineno, stripped[:160],
                ))
    findings.sort(key=lambda f: (_SEV_ORDER.get(f.severity, 9), f.line))
    return findings


def scan_change(old_content: str | None, new_content: str, filename: str) -> list[Finding]:
    """Scan only what a change introduces.

    Findings are kept only if their line is added/modified relative to
    old_content, so an edit to line 200 is never blocked by an issue that
    already existed on line 10.
    """
    all_findings = scan_content(new_content, filename)
    if old_content is None or not all_findings:
        return all_findings
    added: set[int] = set()
    matcher = difflib.SequenceMatcher(
        a=old_content.splitlines(), b=new_content.splitlines(), autojunk=False
    )
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            added.update(range(j1 + 1, j2 + 1))  # 1-based line numbers
    return [f for f in all_findings if f.line in added]


def scan_path(root: Path, target: str = ".") -> list[Finding]:
    """Scan a file or directory tree on disk (the `security_scan` tool)."""
    base = (root / target).resolve() if not os.path.isabs(target) else Path(target)
    findings: list[Finding] = []
    if base.is_file():
        candidates = [base]
    else:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            candidates.extend(Path(dirpath) / n for n in filenames)
    for fp in candidates:
        try:
            if fp.stat().st_size > 1024 * 1024:
                continue
            text = fp.read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = os.path.relpath(fp, root)
        findings.extend(scan_content(text, rel))
    findings.sort(key=lambda f: (_SEV_ORDER.get(f.severity, 9), f.file, f.line))
    return findings


def worst_severity(findings: list[Finding]) -> str:
    if not findings:
        return "CLEAN"
    return min(findings, key=lambda f: _SEV_ORDER.get(f.severity, 9)).severity


def format_report(findings: list[Finding], limit: int = 50) -> str:
    if not findings:
        return "No security findings."
    lines = [f.format() for f in findings[:limit]]
    if len(findings) > limit:
        lines.append(f"… and {len(findings) - limit} more")
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    summary = " · ".join(f"{sev} {n}" for sev, n in sorted(counts.items(), key=lambda kv: _SEV_ORDER.get(kv[0], 9)))
    return "\n".join(lines) + f"\n{len(findings)} finding(s): {summary}"
