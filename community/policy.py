# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
community/policy.py — CI policy gate.

Turns a ScanResult into a pass/fail decision suitable for blocking a CI
pipeline. The gate is deterministic and explainable: every reason a build
fails is reported, and an allowlist lets teams accept findings they have
triaged without disabling the whole gate.

Two complementary controls:
  • fail_on  — a severity floor. Any finding at or above this severity fails
               the gate (default: HIGH → fail on CRITICAL or HIGH).
  • max_*    — explicit per-severity / total budgets (None = unbounded).

Config can be loaded from .tythanai.yml / .tythanai.yaml / .tythanai.json or
passed on the command line. No network, no hidden state — same input, same
verdict.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, List, Optional

if TYPE_CHECKING:
    from community.scanner import ScanResult

# Severity ranking — higher is worse.
_SEV_RANK: Dict[str, int] = {
    "INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4,
}
_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")

# Values that mean "do not gate on severity at all".
_FAIL_ON_DISABLED = {"NONE", "OFF", "NEVER", "", "0"}

_DEFAULT_CONFIG_NAMES = (
    ".tythanai.yml", ".tythanai.yaml", ".tythanai.json",
    "tythanai.yml", "tythanai.yaml", "tythanai.json",
)


def _sev_rank(sev: str) -> int:
    return _SEV_RANK.get(str(sev).upper(), 0)


# ── Policy ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Policy:
    """A CI gate policy. Frozen — evaluation never mutates it."""
    fail_on: str = "HIGH"
    max_critical: Optional[int] = None
    max_high: Optional[int] = None
    max_medium: Optional[int] = None
    max_low: Optional[int] = None
    max_total: Optional[int] = None
    fail_on_scan_errors: bool = False
    ignore_ids: FrozenSet[str] = field(default_factory=frozenset)
    ignore_sources: FrozenSet[str] = field(default_factory=frozenset)

    # ── Constructors ──────────────────────────────────────────────────────────

    @staticmethod
    def default() -> "Policy":
        """Sensible CI default: fail the build on any CRITICAL or HIGH finding."""
        return Policy(fail_on="HIGH")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Policy":
        """
        Build a Policy from a mapping. Accepts the keys at top level or nested
        under a 'gate:' / 'policy:' section, so several config layouts work.
        """
        if not isinstance(data, dict):
            raise ValueError("policy config must be a mapping")
        # Unwrap a nested section if present.
        for section in ("gate", "policy"):
            if isinstance(data.get(section), dict):
                data = data[section]
                break

        def _int_or_none(key: str) -> Optional[int]:
            v = data.get(key)
            if v is None:
                return None
            return int(v)

        def _strset(key: str) -> FrozenSet[str]:
            v = data.get(key) or []
            if isinstance(v, str):
                v = [v]
            return frozenset(str(x).strip() for x in v if str(x).strip())

        fail_on = str(data.get("fail_on", "HIGH")).upper()
        if fail_on not in _SEV_RANK and fail_on not in _FAIL_ON_DISABLED:
            raise ValueError(
                f"invalid fail_on: {fail_on!r} "
                f"(expected one of CRITICAL/HIGH/MEDIUM/LOW/INFO/NONE)"
            )

        return cls(
            fail_on=fail_on,
            max_critical=_int_or_none("max_critical"),
            max_high=_int_or_none("max_high"),
            max_medium=_int_or_none("max_medium"),
            max_low=_int_or_none("max_low"),
            max_total=_int_or_none("max_total"),
            fail_on_scan_errors=bool(data.get("fail_on_scan_errors", False)),
            ignore_ids=_strset("ignore_ids"),
            ignore_sources=_strset("ignore_sources"),
        )

    @classmethod
    def from_file(cls, path: str) -> "Policy":
        """Load a policy from a YAML or JSON file."""
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        data = _load_structured(text, p.suffix)
        return cls.from_dict(data or {})

    @classmethod
    def discover(cls, *search_dirs: str) -> Optional["Policy"]:
        """
        Find the first config file in the given directories and load it.
        Returns None when no config file exists (caller uses the default).
        """
        for d in search_dirs:
            if not d:
                continue
            base = Path(d)
            for name in _DEFAULT_CONFIG_NAMES:
                candidate = base / name
                if candidate.is_file():
                    return cls.from_file(str(candidate))
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def fail_on_rank(self) -> int:
        if self.fail_on in _FAIL_ON_DISABLED:
            return 99  # nothing reaches it
        return _SEV_RANK.get(self.fail_on, _SEV_RANK["HIGH"])

    def is_ignored(self, finding: Dict[str, Any]) -> bool:
        """True when a finding is allowlisted by id or source."""
        ids = {
            str(finding.get(k, "")).strip()
            for k in ("rule_id", "id", "cve", "osv_id")
            if finding.get(k)
        }
        if ids & self.ignore_ids:
            return True
        src = str(finding.get("source", ""))
        return any(src == s or src.startswith(s) for s in self.ignore_sources)


# ── Decision ──────────────────────────────────────────────────────────────────

@dataclass
class GateDecision:
    passed: bool
    reasons: List[str]
    counts: Dict[str, int]
    total: int
    ignored: int
    blocking: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """0 when the gate passes, 1 when it fails — the CI convention."""
        return 0 if self.passed else 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "exit_code": self.exit_code,
            "reasons": self.reasons,
            "counts": self.counts,
            "total": self.total,
            "ignored": self.ignored,
            "blocking_count": len(self.blocking),
        }


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate(result: "ScanResult", policy: Optional[Policy] = None) -> GateDecision:
    """
    Evaluate a scan result against a policy and return a GateDecision.

    Allowlisted findings are removed before any threshold is applied, so an
    accepted finding never trips the gate but is still counted in `ignored`.
    """
    policy = policy or Policy.default()

    considered: List[Dict[str, Any]] = []
    ignored = 0
    for f in result.all_findings:
        if policy.is_ignored(f):
            ignored += 1
        else:
            considered.append(f)

    counts: Dict[str, int] = {s: 0 for s in _SEVERITIES}
    for f in considered:
        sev = str(f.get("severity", "INFO")).upper()
        counts[sev] = counts.get(sev, 0) + 1

    reasons: List[str] = []

    # 1) Severity floor.
    blocking: List[Dict[str, Any]] = []
    if policy.fail_on_rank <= _SEV_RANK["CRITICAL"]:
        blocking = [
            f for f in considered
            if _sev_rank(f.get("severity", "INFO")) >= policy.fail_on_rank
        ]
        if blocking:
            reasons.append(
                f"{len(blocking)} finding(s) at or above severity "
                f"{policy.fail_on} (gate threshold)"
            )

    # 2) Per-severity budgets.
    budget_map = {
        "CRITICAL": policy.max_critical,
        "HIGH": policy.max_high,
        "MEDIUM": policy.max_medium,
        "LOW": policy.max_low,
    }
    for sev, cap in budget_map.items():
        if cap is not None and counts.get(sev, 0) > cap:
            reasons.append(f"{counts[sev]} {sev} finding(s) exceed budget of {cap}")

    # 3) Total budget.
    total_considered = len(considered)
    if policy.max_total is not None and total_considered > policy.max_total:
        reasons.append(
            f"{total_considered} finding(s) exceed total budget of {policy.max_total}"
        )

    # 4) Scan errors (partial scans) — opt-in.
    if policy.fail_on_scan_errors and result.errors:
        reasons.append(f"{len(result.errors)} scanner error(s) during scan")

    passed = not reasons
    return GateDecision(
        passed=passed,
        reasons=reasons,
        counts=counts,
        total=total_considered,
        ignored=ignored,
        blocking=blocking,
    )


# ── Structured-config loading ─────────────────────────────────────────────────

def _load_structured(text: str, suffix: str) -> Any:
    """Parse YAML or JSON. YAML is preferred when available; JSON always works."""
    suffix = (suffix or "").lower()
    if suffix == ".json":
        return json.loads(text)
    # YAML (covers .yml/.yaml and unknown suffixes). PyYAML is a dependency,
    # but we degrade to JSON parsing if it is somehow unavailable.
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        return json.loads(text)
