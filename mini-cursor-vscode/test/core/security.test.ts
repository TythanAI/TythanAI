import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as crypto from "node:crypto";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { formatFindings, scanText, scanWorkspace, shannonEntropy } from "../../src/core/security";
import { Workspace } from "../../src/core/tools";

function rulesFound(findings: { rule: string }[]): Set<string> {
  return new Set(findings.map((f) => f.rule));
}

describe("scanText", () => {
  it("detects an AWS key", () => {
    const findings = scanText('aws_key = "AKIAIOSFODNN7REALKEY"', "cfg.py");
    expect(rulesFound(findings).has("SEC-AWS-KEY")).toBe(true);
    expect(findings[0]?.severity).toBe("CRITICAL");
    expect(findings[0]?.line).toBe(1);
  });

  it("detects a private key and a hardcoded credential", () => {
    const text = '-----BEGIN RSA PRIVATE KEY-----\npassword = "hunter2hunter2"\n';
    const rules = rulesFound(scanText(text, "secrets.txt"));
    expect(rules.has("SEC-PRIVATE-KEY")).toBe(true);
    expect(rules.has("SEC-HARDCODED-CRED")).toBe(true);
  });

  it("downgrades fixture-looking lines", () => {
    const findings = scanText('key = "AKIAIOSFODNN7EXAMPLE"  # example', "docs.py");
    const aws = findings.filter((f) => f.rule === "SEC-AWS-KEY");
    expect(aws.length).toBeGreaterThan(0);
    expect(aws[0]?.severity).toBe("MEDIUM");
  });

  it("detects dangerous Python patterns", () => {
    const text = [
      "import pickle, yaml, subprocess",
      "data = pickle.loads(blob)",
      "cfg = yaml.load(f)",
      "subprocess.run(cmd, shell=True)",
      'cur.execute(f"SELECT * FROM users WHERE id={uid}")',
      "requests.get(url, verify=False)",
    ].join("\n");
    const rules = rulesFound(scanText(text, "app.py"));
    for (const r of ["PY-PICKLE", "PY-YAML-LOAD", "PY-SHELL-TRUE", "PY-SQL-FSTRING", "PY-VERIFY-FALSE"]) {
      expect(rules.has(r)).toBe(true);
    }
  });

  it("does not flag yaml.load with a SafeLoader", () => {
    const findings = scanText("yaml.load(f, Loader=yaml.SafeLoader)", "app.py");
    expect(rulesFound(findings).has("PY-YAML-LOAD")).toBe(false);
  });

  it("finds nothing in clean code", () => {
    const text = "import os\nkey = os.environ['API_KEY']\nprint('hello')\n";
    expect(scanText(text, "clean.py")).toEqual([]);
  });

  it("detects the newer secret rules", () => {
    const text = [
      `stripe = "sk_live_${"a1B2c3D4e5F6g7H8i9J0k1L2"}"`,
      `g = "AIza${"SyA" + "x".repeat(32)}"`,
      `auth = {"Authorization": "Bearer abcdefghij1234567890XYZ"}`,
    ].join("\n");
    const rules = rulesFound(scanText(text, "keys.py"));
    for (const r of ["SEC-STRIPE-KEY", "SEC-GOOGLE-KEY", "SEC-BEARER-TOKEN"]) {
      expect(rules.has(r)).toBe(true);
    }
  });

  it("detects the newer code rules and ignores localhost http", () => {
    const text = [
      "cipher = AES.new(key, AES.MODE_ECB)",
      "token = str(random.randint(0, 999999))",
      "path = tempfile.mktemp()",
      'url = "http://api.example.com/v1"',
      'safe = "http://localhost:8080"',
    ].join("\n");
    const rules = rulesFound(scanText(text, "app.py"));
    for (const r of ["PY-WEAK-CIPHER", "PY-INSECURE-RANDOM", "PY-MKTEMP", "NET-PLAIN-HTTP"]) {
      expect(rules.has(r)).toBe(true);
    }
    expect(scanText(text, "app.py").filter((f) => f.rule === "NET-PLAIN-HTTP")).toHaveLength(1);
  });

  it("detects high-entropy secrets by context", () => {
    // 48 random bytes (64 base64url chars): long enough that the measured
    // Shannon entropy reliably clears the 4.4 bits/char threshold — a
    // shorter sample has enough variance to occasionally (rarely) dip below
    // it by chance, which would make this test flaky.
    const randomKey = crypto.randomBytes(48).toString("base64url");
    const findings = scanText(`db_key = "${randomKey}"\n`, "cfg.py");
    expect(rulesFound(findings).has("SEC-HIGH-ENTROPY")).toBe(true);

    expect(rulesFound(scanText('key = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n', "cfg.py")).has("SEC-HIGH-ENTROPY")).toBe(
      false,
    );
    expect(rulesFound(scanText(`greeting = "${randomKey}"\n`, "cfg.py")).has("SEC-HIGH-ENTROPY")).toBe(false);
  });

  it("skips the entropy check when a specific rule already fired", () => {
    const findings = scanText('token = "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"\n', "cfg.py");
    const rules = rulesFound(findings);
    expect(rules.has("SEC-GITHUB-TOKEN")).toBe(true);
    expect(rules.has("SEC-HIGH-ENTROPY")).toBe(false);
  });
});

describe("shannonEntropy", () => {
  it("is zero for an empty string", () => {
    expect(shannonEntropy("")).toBe(0);
  });

  it("is higher for random-looking strings than repeated characters", () => {
    expect(shannonEntropy("aaaaaaaaaa")).toBeLessThan(shannonEntropy("aZ3kQ9mP1x"));
  });
});

describe("scanWorkspace", () => {
  let dir: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "mini-cursor-sec-"));
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("scans the workspace, skips junk dirs and binaries, sorts by severity", () => {
    fs.writeFileSync(path.join(dir, "a.py"), 'token = "AKIAIOSFODNN7REALKEY"\n');
    fs.writeFileSync(path.join(dir, "b.py"), "x = yaml.load(f)\n");
    fs.mkdirSync(path.join(dir, ".git"));
    fs.writeFileSync(path.join(dir, ".git", "leaked.py"), 'p = "AKIAIOSFODNN7REALKEY"\n');
    fs.writeFileSync(path.join(dir, "image.png"), "AKIAIOSFODNN7REALKEY");

    const findings = scanWorkspace(new Workspace(dir));
    const paths = findings.map((f) => f.path);
    expect(paths).toContain("a.py");
    expect(paths).toContain("b.py");
    expect(paths.some((p) => p.includes(".git") || p.endsWith(".png"))).toBe(false);
    expect(findings[0]?.severity).toBe("CRITICAL");
  });

  it("scans a single file when given a subpath", () => {
    fs.writeFileSync(path.join(dir, "ok.py"), "print('hi')\n");
    fs.writeFileSync(path.join(dir, "bad.py"), "eval(user_input)\n");
    const findings = scanWorkspace(new Workspace(dir), "bad.py");
    expect(rulesFound(findings)).toEqual(new Set(["PY-EVAL"]));
  });

  it("skips lockfiles and minified bundles", () => {
    fs.writeFileSync(path.join(dir, "package-lock.json"), '{"password": "supersecretvalue123"}\n');
    fs.writeFileSync(path.join(dir, "app.min.js"), 'password = "supersecretvalue123"\n');
    expect(scanWorkspace(new Workspace(dir))).toEqual([]);
  });
});

describe("formatFindings", () => {
  let dir: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "mini-cursor-sec-fmt-"));
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("reports findings with path, line and a summary", () => {
    fs.writeFileSync(path.join(dir, "bad.py"), 'password = "supersecretvalue"\n');
    const report = formatFindings(scanWorkspace(new Workspace(dir)));
    expect(report).toContain("SEC-HARDCODED-CRED");
    expect(report).toContain("bad.py:1");
    expect(report).toContain("Summary:");
  });

  it("reports a clean message for no findings", () => {
    expect(formatFindings([])).toContain("No security findings");
  });
});
