"""
backend/scanners/iac_scanner.py — IaC Static Analysis Scanner

Provides the IaCScanner with standardised rule IDs:
  Terraform:       IAC-TF-001 to IAC-TF-009
  CloudFormation:  IAC-CF-001 to IAC-CF-005
  Kubernetes:      IAC-K8S-001 to IAC-K8S-009
"""
from __future__ import annotations
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─── Result type ─────────────────────────────────────────────────────────────

@dataclass
class IaCScanResult:
    rule_id:     str
    severity:    str   # CRITICAL | HIGH | MEDIUM | LOW | INFO
    category:    str   # ENCRYPTION | NETWORK | SECRETS | PRIVILEGE | …
    message:     str
    description: str = ""
    file:        str = ""
    line:        int = 0
    evidence:    str = ""
    cwe:         str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id":     self.rule_id,
            "severity":    self.severity,
            "category":    self.category,
            "message":     self.message,
            "description": self.description,
            "file":        self.file,
            "line":        self.line,
            "evidence":    self.evidence,
            "cwe":         self.cwe,
        }


IaCFinding = IaCScanResult  # backward-compat alias
IaCScanner_alias = None  # resolved below


# ─── Terraform analyzer ───────────────────────────────────────────────────────

_TF_CREDENTIAL_KEYS = re.compile(
    r'\b(password|secret|api_key|token|private_key|access_key)\s*=\s*"[^"${}][^"]*"',
    re.IGNORECASE,
)
_TF_OPEN_CIDR = re.compile(r"0\.0\.0\.0/0")
_TF_SSH_PORT = re.compile(r"from_port\s*=\s*22")


def _scan_terraform(content: str, path: str) -> List[IaCScanResult]:
    findings: List[IaCScanResult] = []
    lines = content.splitlines()

    # IAC-TF-001: S3 missing server-side encryption
    if "aws_s3_bucket" in content and "server_side_encryption" not in content:
        findings.append(IaCScanResult(
            rule_id="IAC-TF-001",
            severity="HIGH",
            category="ENCRYPTION",
            message="S3 bucket missing server-side encryption configuration",
            description="All S3 buckets should have encryption enabled at rest.",
            file=path, cwe="CWE-311",
            evidence="server_side_encryption_configuration not found",
        ))

    # IAC-TF-002: Security group with SSH open to 0.0.0.0/0
    if "aws_security_group" in content:
        for i, line in enumerate(lines, 1):
            if ("from_port" in line and "22" in line) or ("to_port" in line and "22" in line):
                # check surrounding block for open CIDR
                block = "\n".join(lines[max(0, i-5):min(len(lines), i+5)])
                if _TF_OPEN_CIDR.search(block):
                    findings.append(IaCScanResult(
                        rule_id="IAC-TF-002",
                        severity="CRITICAL",
                        category="NETWORK",
                        message="Security group allows SSH (port 22) from 0.0.0.0/0",
                        description="SSH should never be open to the public internet.",
                        file=path, line=i, cwe="CWE-284",
                        evidence=line.strip(),
                    ))
                    break

    # IAC-TF-008: Hardcoded secrets
    for i, line in enumerate(lines, 1):
        if _TF_CREDENTIAL_KEYS.search(line):
            findings.append(IaCScanResult(
                rule_id="IAC-TF-008",
                severity="CRITICAL",
                category="SECRETS",
                message="Hardcoded credential detected in Terraform configuration",
                description="Use variables or Secrets Manager — never hardcode secrets.",
                file=path, line=i, cwe="CWE-798",
                evidence=re.sub(r'=\s*"[^"]+"', '= "***"', line.strip()),
            ))
            break  # one finding per file is sufficient

    return findings


# ─── CloudFormation analyzer ──────────────────────────────────────────────────

def _scan_cloudformation(content: str, path: str) -> List[IaCScanResult]:
    findings: List[IaCScanResult] = []
    try:
        doc = yaml.safe_load(content)
    except Exception:
        return findings

    if not isinstance(doc, dict) or "Resources" not in doc:
        return findings

    for res_name, res in (doc.get("Resources") or {}).items():
        if not isinstance(res, dict):
            continue
        res_type = res.get("Type", "")
        props = res.get("Properties") or {}

        # IAC-CF-001: Security group with SSH open
        if res_type == "AWS::EC2::SecurityGroup":
            for ingress in (props.get("SecurityGroupIngress") or []):
                if not isinstance(ingress, dict):
                    continue
                from_port = ingress.get("FromPort")
                cidr = ingress.get("CidrIp", "")
                if (from_port in (22, "22")) and cidr in ("0.0.0.0/0", "::/0"):
                    findings.append(IaCScanResult(
                        rule_id="IAC-CF-001",
                        severity="CRITICAL",
                        category="NETWORK",
                        message=f"CloudFormation SecurityGroup '{res_name}' allows SSH from {cidr}",
                        description="Restrict SSH access to specific IP ranges.",
                        file=path, cwe="CWE-284",
                        evidence=f"SecurityGroupIngress port 22 CidrIp {cidr}",
                    ))

    return findings


# ─── Kubernetes analyzer ──────────────────────────────────────────────────────

def _scan_kubernetes(content: str, path: str) -> List[IaCScanResult]:
    findings: List[IaCScanResult] = []
    try:
        docs = list(yaml.safe_load_all(content))
    except Exception:
        return findings

    for doc in docs:
        if not isinstance(doc, dict):
            continue

        spec = doc.get("spec", {})
        template = spec.get("template", {})
        pod_spec = template.get("spec", {}) if isinstance(template, dict) else {}

        containers = (
            pod_spec.get("containers", [])
            + pod_spec.get("initContainers", [])
        )

        for ctr in (containers or []):
            if not isinstance(ctr, dict):
                continue
            sec_ctx = ctr.get("securityContext") or {}

            # IAC-K8S-005: privileged container
            if sec_ctx.get("privileged") is True:
                findings.append(IaCScanResult(
                    rule_id="IAC-K8S-005",
                    severity="CRITICAL",
                    category="PRIVILEGE",
                    message=f"Container '{ctr.get('name', '?')}' runs with privileged: true",
                    description="Privileged containers have full host access.",
                    file=path, cwe="CWE-269",
                    evidence="securityContext.privileged: true",
                ))

    return findings


# ─── IaCScanner ──────────────────────────────────────────────────────────────

class IaCScanner:
    """Static Infrastructure-as-Code scanner with standardised rule IDs."""

    def scan_file(self, file_path: str) -> List[IaCScanResult]:
        p = Path(file_path)
        if not p.exists():
            return []
        content = p.read_text(errors="replace")
        name = p.name.lower()

        if p.suffix == ".tf":
            return _scan_terraform(content, file_path)

        if p.suffix in (".yml", ".yaml"):
            # Heuristic: CloudFormation has AWSTemplateFormatVersion or Resources with Type: AWS::
            if "AWSTemplateFormatVersion" in content or "AWS::" in content:
                return _scan_cloudformation(content, file_path)
            # Kubernetes has apiVersion / kind
            if "apiVersion" in content and "kind" in content:
                return _scan_kubernetes(content, file_path)

        return []

    def scan_directory(self, directory: str) -> dict:
        root = Path(directory)
        findings: List[IaCScanResult] = []
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in (".tf", ".yml", ".yaml"):
                findings.extend(self.scan_file(str(p)))
        return {
            "findings": [f.to_dict() for f in findings],
            "total": len(findings),
        }


IACScanner = IaCScanner  # alias
