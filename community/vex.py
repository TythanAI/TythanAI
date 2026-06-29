# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
community/vex.py — OpenVEX 0.2.0 document generation.

VEX (Vulnerability Exploitability eXchange) communicates the exploitability
status of *known* vulnerabilities (CVE / GHSA / OSV) in shipped products.
This module turns the SCA findings of a scan into a spec-compliant OpenVEX
document so downstream consumers (Grype, Trivy, scanners in CI) can filter
or act on the vulnerabilities TythanAI surfaced.

Honest boundaries (documented, not hidden):
  • VEX only describes *vulnerabilities* — entries with a CVE/GHSA/OSV id.
    SAST / secrets / IaC findings are NOT vulnerabilities and are correctly
    excluded from the VEX document (use SARIF for those).
  • Every emitted statement has status "affected": the scanner observed a
    vulnerable component *version* in a manifest. We do not assert
    "not_affected"/"fixed" — that requires reachability/triage we do not
    perform here, so we never fabricate a clean status.
  • The product is identified by a Package-URL (purl) inferred from the
    ecosystem or the manifest file. When the ecosystem cannot be determined
    we fall back to pkg:generic and say so — accuracy over guesswork.

Spec: https://github.com/openvex/spec  (OpenVEX v0.2.0)
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:                      # avoid a hard import cycle at runtime
    from community.scanner import ScanResult

_OPENVEX_CONTEXT = "https://openvex.dev/ns/v0.2.0"
_VERSION = "1.0.0"
_AUTHOR = "TythanAI Community Edition"
_TOOLING = f"TythanAI-Community/{_VERSION}"

# OpenVEX status vocabulary (spec §Status Labels)
STATUS_AFFECTED = "affected"
STATUS_NOT_AFFECTED = "not_affected"
STATUS_FIXED = "fixed"
STATUS_UNDER_INVESTIGATION = "under_investigation"

# ── purl type resolution ──────────────────────────────────────────────────────

# OSV ecosystem name → purl type (https://github.com/package-url/purl-spec)
_PURL_BY_ECOSYSTEM: Dict[str, str] = {
    "pypi": "pypi",
    "npm": "npm",
    "go": "golang",
    "crates.io": "cargo",
    "cargo": "cargo",
    "rubygems": "gem",
    "maven": "maven",
    "nuget": "nuget",
    "hex": "hex",
    "pub": "pub",
    "packagist": "composer",
    "composer": "composer",
}

# manifest filename fragment → purl type (fallback when ecosystem is absent)
_PURL_BY_MANIFEST: Dict[str, str] = {
    "requirements": "pypi",
    "pyproject.toml": "pypi",
    "setup.cfg": "pypi",
    "setup.py": "pypi",
    "pipfile": "pypi",
    "package.json": "npm",
    "package-lock.json": "npm",
    "yarn.lock": "npm",
    "go.mod": "golang",
    "go.sum": "golang",
    "cargo.toml": "cargo",
    "cargo.lock": "cargo",
    "gemfile": "gem",
    "pom.xml": "maven",
    "build.gradle": "maven",
    "composer.json": "composer",
}

_VULN_ID_RE = re.compile(r"^(CVE-\d{4}-\d+|GHSA-[\w-]+|OSV-[\w.-]+|[A-Z]+-\d{4}-\d+)$", re.I)


def _infer_purl_type(finding: Dict[str, Any]) -> Optional[str]:
    """Resolve a purl type from an explicit ecosystem or the manifest filename."""
    eco = str(finding.get("ecosystem", "")).strip().lower()
    if eco and eco in _PURL_BY_ECOSYSTEM:
        return _PURL_BY_ECOSYSTEM[eco]

    fname = Path(str(finding.get("file", ""))).name.lower()
    if fname:
        for fragment, ptype in _PURL_BY_MANIFEST.items():
            if fragment in fname:
                return ptype
    return None


def _purl(finding: Dict[str, Any]) -> str:
    """
    Build a Package-URL for the vulnerable component.

    Falls back to pkg:generic when the ecosystem cannot be determined, so the
    statement is still valid and traceable rather than silently dropped.
    """
    name = str(finding.get("package", "")).strip()
    version = str(finding.get("installed_version", "")).strip()
    ptype = _infer_purl_type(finding) or "generic"

    if not name:
        # No component name — identify by file so the statement stays anchored.
        anchor = str(finding.get("file", "unknown")).strip() or "unknown"
        base = f"pkg:generic/{_purl_quote(anchor)}"
    else:
        base = f"pkg:{ptype}/{_purl_quote(name)}"

    if version:
        base += f"@{_purl_quote(version)}"
    return base


def _purl_quote(value: str) -> str:
    """Percent-encode the characters purl reserves, keeping it readable."""
    out = []
    for ch in value:
        if ch.isalnum() or ch in "-._~/":
            out.append(ch)
        else:
            out.append("%" + format(ord(ch), "02X"))
    return "".join(out)


# ── vulnerability identity ────────────────────────────────────────────────────

def _vuln_identity(finding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract the canonical vulnerability identity from a finding.

    Returns None when the finding carries no recognised vulnerability id —
    those findings (SAST/secrets/IaC) are not VEX-eligible.
    """
    candidates: List[str] = []
    for key in ("cve", "id", "osv_id", "rule_id"):
        v = finding.get(key)
        if v:
            candidates.append(str(v).strip())
    aliases = finding.get("aliases") or []
    if isinstance(aliases, (list, tuple)):
        candidates.extend(str(a).strip() for a in aliases if a)

    # Prefer a CVE, then GHSA, then any recognised id.
    name = None
    for c in candidates:
        if c.upper().startswith("CVE-"):
            name = c
            break
    if name is None:
        for c in candidates:
            if c.upper().startswith("GHSA-"):
                name = c
                break
    if name is None:
        for c in candidates:
            if _VULN_ID_RE.match(c):
                name = c
                break
    if name is None:
        return None

    # Collect distinct aliases (everything recognised that isn't the primary).
    seen = {name.upper()}
    alias_out: List[str] = []
    for c in candidates:
        if _VULN_ID_RE.match(c) and c.upper() not in seen:
            seen.add(c.upper())
            alias_out.append(c)

    identity: Dict[str, Any] = {"name": name}
    if alias_out:
        identity["aliases"] = alias_out
    return identity


# ── statement construction ────────────────────────────────────────────────────

def _statements(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build OpenVEX statements, one per (vulnerability, product) pair.

    Deduplicates so re-listed CVEs collapse into a single statement, and
    aggregates products affected by the same vulnerability.
    """
    # key: vuln name → {"vuln": identity, "products": {purl: action}}
    grouped: Dict[str, Dict[str, Any]] = {}

    for f in findings:
        identity = _vuln_identity(f)
        if identity is None:
            continue
        key = identity["name"].upper()
        purl = _purl(f)

        bucket = grouped.setdefault(key, {"vuln": identity, "products": {}})
        # Keep the richest identity (one with aliases) if duplicates differ.
        if "aliases" in identity and "aliases" not in bucket["vuln"]:
            bucket["vuln"] = identity

        action = _action_statement(f)
        # First non-empty action wins for a given product.
        if purl not in bucket["products"] or not bucket["products"][purl]:
            bucket["products"][purl] = action

    statements: List[Dict[str, Any]] = []
    for key in sorted(grouped):
        entry = grouped[key]
        products = sorted(entry["products"])
        statement: Dict[str, Any] = {
            "vulnerability": entry["vuln"],
            "products": [{"@id": p} for p in products],
            "status": STATUS_AFFECTED,
            "status_notes": (
                "TythanAI detected a known-vulnerable component version in a "
                "dependency manifest (static SCA). Exploitability in this "
                "specific application was not assessed."
            ),
        }
        # action_statement is recommended for 'affected' (spec §Statements).
        actions = [a for a in entry["products"].values() if a]
        if actions:
            # Use the most common / first remediation hint.
            statement["action_statement"] = actions[0]
        statements.append(statement)

    return statements


def _action_statement(finding: Dict[str, Any]) -> str:
    """Remediation hint for an 'affected' statement, if known."""
    rec = str(finding.get("recommendation", "")).strip()
    if rec:
        return rec
    pkg = str(finding.get("package", "")).strip()
    fixed = str(finding.get("fixed_in", "")).strip()
    if pkg and fixed and fixed.lower() not in ("", "latest", "unknown"):
        return f"Upgrade {pkg} to >= {fixed}."
    if pkg:
        return f"Upgrade {pkg} to a patched release."
    return ""


# ── document assembly ─────────────────────────────────────────────────────────

def to_openvex(result: "ScanResult") -> Dict[str, Any]:
    """
    Produce an OpenVEX 0.2.0 document from a ScanResult.

    Only vulnerability findings (those with a CVE/GHSA/OSV id) become
    statements; everything else is intentionally excluded.
    """
    statements = _statements(list(result.all_findings))

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    doc_id = _document_id(statements)

    doc: Dict[str, Any] = {
        "@context": _OPENVEX_CONTEXT,
        "@id": doc_id,
        "author": _AUTHOR,
        "role": "Security Scanner",
        "timestamp": now,
        "last_updated": now,
        "version": 1,
        "tooling": _TOOLING,
        "statements": statements,
    }
    return doc


def _document_id(statements: List[Dict[str, Any]]) -> str:
    """
    Content-addressed @id: identical findings → identical id across runs,
    which keeps the document diff-stable in CI.
    """
    material = json.dumps(
        [(s["vulnerability"]["name"], [p["@id"] for p in s["products"]]) for s in statements],
        sort_keys=True,
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"https://tythanai.io/vex/{digest}"


def write_vex(result: "ScanResult", output_path: str) -> Dict[str, Any]:
    """Serialise the OpenVEX document to disk; returns the document dict."""
    doc = to_openvex(result)
    Path(output_path).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc
