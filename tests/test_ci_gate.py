# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tests/test_ci_gate.py — OpenVEX + policy gate + `tythanai ci` command.

These tests enforce hard guarantees the CI gate depends on:
  • VEX is spec-shaped and only carries real vulnerabilities (no SAST noise).
  • The policy gate is deterministic and explainable.
  • `tythanai ci` exits 0 on a clean gate and non-zero when it fails.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from community.policy import GateDecision, Policy, evaluate
from community.scanner import ScanResult
from community.vex import (
    _purl,
    _vuln_identity,
    to_openvex,
    write_vex,
)

# ─── fixtures ─────────────────────────────────────────────────────────────────

def _result_with_cves() -> ScanResult:
    r = ScanResult(target="/tmp/demo")
    r.sca_findings = [
        {
            "severity": "CRITICAL", "title": "pyyaml RCE", "file": "requirements.txt",
            "line": 0, "cve": "CVE-2020-14343", "package": "pyyaml",
            "installed_version": "5.3.1", "fixed_in": "5.4", "source": "sca",
            "recommendation": "Upgrade pyyaml to >= 5.4", "ecosystem": "PyPI",
        },
        {
            "severity": "HIGH", "title": "lodash command injection", "file": "package.json",
            "line": 0, "cve": "CVE-2021-23337", "package": "lodash",
            "installed_version": "4.17.0", "fixed_in": "4.17.21", "source": "sca",
        },
    ]
    r.sast_findings = [
        {"severity": "HIGH", "title": "eval() usage", "file": "app.py", "line": 3,
         "rule_id": "PY001", "source": "sast"},
    ]
    return r


# ─── VEX ──────────────────────────────────────────────────────────────────────

class TestVEX:
    def test_context_and_version(self):
        doc = to_openvex(_result_with_cves())
        assert doc["@context"] == "https://openvex.dev/ns/v0.2.0"
        assert doc["version"] == 1
        assert doc["@id"].startswith("https://tythanai.io/vex/")

    def test_required_top_level_fields(self):
        doc = to_openvex(_result_with_cves())
        for key in ("@context", "@id", "author", "timestamp", "version", "statements"):
            assert key in doc, f"missing {key}"

    def test_only_vulnerabilities_become_statements(self):
        # 3 findings in, but only the 2 with CVEs are VEX-eligible.
        doc = to_openvex(_result_with_cves())
        names = {s["vulnerability"]["name"] for s in doc["statements"]}
        assert names == {"CVE-2020-14343", "CVE-2021-23337"}
        assert "PY001" not in names  # SAST rule must never appear in VEX

    def test_statement_status_is_affected(self):
        doc = to_openvex(_result_with_cves())
        for s in doc["statements"]:
            assert s["status"] == "affected"
            assert s["products"]
            assert all("@id" in p for p in s["products"])

    def test_action_statement_present(self):
        doc = to_openvex(_result_with_cves())
        by_name = {s["vulnerability"]["name"]: s for s in doc["statements"]}
        assert "Upgrade" in by_name["CVE-2020-14343"]["action_statement"]

    def test_purl_pypi(self):
        f = {"package": "pyyaml", "installed_version": "5.3.1", "ecosystem": "PyPI"}
        assert _purl(f) == "pkg:pypi/pyyaml@5.3.1"

    def test_purl_npm_inferred_from_manifest(self):
        f = {"package": "lodash", "installed_version": "4.17.0", "file": "x/package.json"}
        assert _purl(f) == "pkg:npm/lodash@4.17.0"

    def test_purl_generic_fallback(self):
        f = {"package": "weird", "installed_version": "1.0"}
        assert _purl(f).startswith("pkg:generic/weird@1.0")

    def test_vuln_identity_prefers_cve(self):
        ident = _vuln_identity({"id": "OSV-2020-x", "cve": "CVE-2020-14343",
                                "aliases": ["GHSA-abc-def"]})
        assert ident["name"] == "CVE-2020-14343"

    def test_vuln_identity_none_for_sast(self):
        assert _vuln_identity({"rule_id": "PY001", "title": "eval"}) is None

    def test_deduplicates_same_cve_same_product(self):
        r = ScanResult(target="/tmp/x")
        r.sca_findings = [
            {"severity": "CRITICAL", "cve": "CVE-2020-14343", "package": "pyyaml",
             "installed_version": "5.3.1", "ecosystem": "PyPI", "source": "sca"},
            {"severity": "CRITICAL", "cve": "CVE-2020-14343", "package": "pyyaml",
             "installed_version": "5.3.1", "ecosystem": "PyPI", "source": "sca"},
        ]
        doc = to_openvex(r)
        assert len(doc["statements"]) == 1
        assert len(doc["statements"][0]["products"]) == 1

    def test_document_id_is_content_stable(self):
        a = to_openvex(_result_with_cves())["@id"]
        b = to_openvex(_result_with_cves())["@id"]
        assert a == b  # same findings → same id (diff-stable in CI)

    def test_empty_result_valid_doc(self):
        doc = to_openvex(ScanResult(target="/tmp/clean"))
        assert doc["statements"] == []
        assert doc["@context"].startswith("https://openvex.dev/")

    def test_write_vex_creates_valid_json(self, tmp_path):
        out = str(tmp_path / "v.json")
        write_vex(_result_with_cves(), out)
        data = json.loads(Path(out).read_text())
        assert data["@context"] == "https://openvex.dev/ns/v0.2.0"
        assert len(data["statements"]) == 2


# ─── Policy ───────────────────────────────────────────────────────────────────

class TestPolicy:
    def test_default_fails_on_high(self):
        d = evaluate(_result_with_cves(), Policy.default())
        assert d.passed is False
        assert d.exit_code == 1
        assert d.reasons

    def test_clean_result_passes(self):
        d = evaluate(ScanResult(target="/tmp/clean"), Policy.default())
        assert d.passed is True
        assert d.exit_code == 0
        assert d.reasons == []

    def test_fail_on_none_disables_severity_gate(self):
        d = evaluate(_result_with_cves(), Policy(fail_on="NONE"))
        assert d.passed is True

    def test_fail_on_critical_ignores_high(self):
        r = ScanResult(target="/tmp/x")
        r.sast_findings = [{"severity": "HIGH", "rule_id": "X", "source": "sast"}]
        d = evaluate(r, Policy(fail_on="CRITICAL"))
        assert d.passed is True

    def test_max_total_budget(self):
        r = ScanResult(target="/tmp/x")
        r.sast_findings = [{"severity": "LOW", "source": "sast"} for _ in range(5)]
        d = evaluate(r, Policy(fail_on="NONE", max_total=3))
        assert d.passed is False
        assert any("total budget" in x for x in d.reasons)

    def test_per_severity_budget(self):
        r = ScanResult(target="/tmp/x")
        r.sca_findings = [{"severity": "MEDIUM", "source": "sca"} for _ in range(4)]
        d = evaluate(r, Policy(fail_on="NONE", max_medium=2))
        assert d.passed is False
        assert any("MEDIUM" in x for x in d.reasons)

    def test_ignore_ids_allowlist(self):
        d = evaluate(
            _result_with_cves(),
            Policy(fail_on="HIGH", ignore_ids=frozenset({"CVE-2020-14343",
                                                          "CVE-2021-23337", "PY001"})),
        )
        assert d.ignored == 3
        assert d.passed is True

    def test_ignore_sources_allowlist(self):
        d = evaluate(
            _result_with_cves(),
            Policy(fail_on="HIGH", ignore_sources=frozenset({"sca", "sast"})),
        )
        assert d.passed is True
        assert d.ignored == 3

    def test_fail_on_scan_errors(self):
        r = ScanResult(target="/tmp/x")
        r.errors = ["SAST: boom"]
        d = evaluate(r, Policy(fail_on="NONE", fail_on_scan_errors=True))
        assert d.passed is False

    def test_decision_to_dict(self):
        d = evaluate(_result_with_cves(), Policy.default())
        payload = d.to_dict()
        assert payload["passed"] is False
        assert payload["exit_code"] == 1
        assert "counts" in payload

    def test_evaluate_does_not_mutate_result(self):
        r = _result_with_cves()
        before = len(r.all_findings)
        evaluate(r, Policy.default())
        assert len(r.all_findings) == before


class TestPolicyConfig:
    def test_from_dict_basic(self):
        p = Policy.from_dict({"fail_on": "critical", "max_total": 10})
        assert p.fail_on == "CRITICAL"
        assert p.max_total == 10

    def test_from_dict_nested_section(self):
        p = Policy.from_dict({"gate": {"fail_on": "medium"}})
        assert p.fail_on == "MEDIUM"

    def test_from_dict_invalid_fail_on(self):
        with pytest.raises(ValueError):
            Policy.from_dict({"fail_on": "BOGUS"})

    def test_from_file_json(self, tmp_path):
        cfg = tmp_path / ".tythanai.json"
        cfg.write_text(json.dumps({"fail_on": "LOW", "ignore_ids": ["CVE-1"]}))
        p = Policy.from_file(str(cfg))
        assert p.fail_on == "LOW"
        assert "CVE-1" in p.ignore_ids

    def test_discover_finds_config(self, tmp_path):
        (tmp_path / ".tythanai.json").write_text(json.dumps({"fail_on": "MEDIUM"}))
        p = Policy.discover(str(tmp_path))
        assert p is not None
        assert p.fail_on == "MEDIUM"

    def test_discover_returns_none_when_absent(self, tmp_path):
        assert Policy.discover(str(tmp_path)) is None

    def test_from_file_yaml(self, tmp_path):
        pytest.importorskip("yaml")
        cfg = tmp_path / ".tythanai.yml"
        cfg.write_text("fail_on: HIGH\nmax_critical: 0\nignore_ids:\n  - CVE-2020-14343\n")
        p = Policy.from_file(str(cfg))
        assert p.fail_on == "HIGH"
        assert p.max_critical == 0
        assert "CVE-2020-14343" in p.ignore_ids


# ─── `tythanai ci` CLI ────────────────────────────────────────────────────────

class TestCICommand:
    _ROOT = Path(__file__).resolve().parent.parent

    def _run(self, *args, cwd=None):
        cmd = [sys.executable, str(self._ROOT / "tythanai_community_cli.py"), "ci", *args]
        return subprocess.run(cmd, capture_output=True, text=True,
                              cwd=str(cwd or self._ROOT))

    def _vuln_project(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("pyyaml==5.3.1\n")
        return tmp_path

    def test_ci_clean_dir_passes(self, tmp_path):
        (tmp_path / "ok.txt").write_text("nothing to see")
        r = self._run(str(tmp_path), "--no-artifacts", "--quiet", cwd=tmp_path)
        assert r.returncode == 0
        assert "PASS" in r.stdout

    def test_ci_writes_default_artifacts(self, tmp_path):
        proj = self._vuln_project(tmp_path)
        self._run(str(proj), "--no-sast", "--no-secrets", "--no-iac",
                  "--no-web3", "--quiet", cwd=proj)
        assert (proj / "tythanai.sarif").exists()
        assert (proj / "tythanai.openvex.json").exists()
        vex = json.loads((proj / "tythanai.openvex.json").read_text())
        assert vex["@context"].startswith("https://openvex.dev/")

    def test_ci_exit_zero_flag(self, tmp_path):
        proj = self._vuln_project(tmp_path)
        r = self._run(str(proj), "--no-sast", "--no-secrets", "--no-iac",
                      "--no-web3", "--no-artifacts", "--exit-zero", "--quiet", cwd=proj)
        assert r.returncode == 0

    def test_ci_fail_on_none_passes(self, tmp_path):
        proj = self._vuln_project(tmp_path)
        r = self._run(str(proj), "--no-sast", "--no-secrets", "--no-iac", "--no-web3",
                      "--no-artifacts", "--fail-on", "NONE", "--quiet", cwd=proj)
        assert r.returncode == 0

    def test_ci_nonexistent_target(self):
        r = self._run("/nonexistent/xyz", "--no-artifacts", "--quiet")
        assert r.returncode == 2

    def test_ci_custom_artifact_paths(self, tmp_path):
        proj = self._vuln_project(tmp_path)
        sarif = tmp_path / "custom.sarif"
        vex = tmp_path / "custom.vex.json"
        self._run(str(proj), "--no-sast", "--no-secrets", "--no-iac", "--no-web3",
                  "--sarif", str(sarif), "--vex", str(vex), "--quiet", cwd=proj)
        assert sarif.exists()
        assert vex.exists()

    def test_ci_respects_discovered_policy(self, tmp_path):
        proj = self._vuln_project(tmp_path)
        (proj / ".tythanai.json").write_text(json.dumps({"fail_on": "NONE"}))
        r = self._run(str(proj), "--no-sast", "--no-secrets", "--no-iac", "--no-web3",
                      "--no-artifacts", "--quiet", cwd=proj)
        # discovered policy disables severity gate → clean pass
        assert r.returncode == 0
