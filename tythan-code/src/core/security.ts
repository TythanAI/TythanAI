/**
 * Built-in security scanner — ported line-for-line (rules and behavior) from
 * the Python mini-cursor CLI's security.py. Fast, offline, regex-based
 * checks for the highest-impact classes of issues: leaked secrets,
 * dangerous code patterns, and insecure configuration.
 */

import * as fs from "node:fs";
import * as path from "node:path";

import { SKIP_DIRS, Workspace, walkFiles } from "./tools";

export const MAX_FILE_BYTES = 1_000_000;
export const MAX_FINDINGS = 200;

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM";

export interface Finding {
  rule: string;
  severity: Severity;
  message: string;
  path: string;
  line: number;
  snippet: string;
}

interface Rule {
  id: string;
  severity: Severity;
  message: string;
  regex: RegExp;
}

const RULES: Rule[] = [
  // --- secrets -------------------------------------------------------------
  { id: "SEC-AWS-KEY", severity: "CRITICAL", message: "AWS access key ID in source", regex: /\bAKIA[0-9A-Z]{16}\b/ },
  {
    id: "SEC-PRIVATE-KEY",
    severity: "CRITICAL",
    message: "Private key material in source",
    regex: /-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----/,
  },
  {
    id: "SEC-GITHUB-TOKEN",
    severity: "CRITICAL",
    message: "GitHub token in source",
    regex: /\bgh[pousr]_[A-Za-z0-9]{20,}\b/,
  },
  {
    id: "SEC-SLACK-TOKEN",
    severity: "CRITICAL",
    message: "Slack token in source",
    regex: /\bxox[baprs]-[A-Za-z0-9-]{10,}\b/,
  },
  {
    id: "SEC-API-PROVIDER-KEY",
    severity: "CRITICAL",
    message: "AI provider API key in source",
    regex: /\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b/,
  },
  {
    id: "SEC-STRIPE-KEY",
    severity: "CRITICAL",
    message: "Stripe live secret key in source",
    regex: /\bsk_live_[0-9a-zA-Z]{24,}\b/,
  },
  {
    id: "SEC-GOOGLE-KEY",
    severity: "CRITICAL",
    message: "Google API key in source",
    regex: /\bAIza[0-9A-Za-z_-]{35}\b/,
  },
  {
    id: "SEC-TELEGRAM-TOKEN",
    severity: "CRITICAL",
    message: "Telegram bot token in source",
    regex: /\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b/,
  },
  {
    id: "SEC-JWT-HARDCODED",
    severity: "MEDIUM",
    message: "Hardcoded JWT in source",
    regex: /\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}/,
  },
  {
    id: "SEC-BEARER-TOKEN",
    severity: "HIGH",
    message: "Hardcoded Bearer token",
    regex: /authorization['"]?\s*[:=]\s*["']bearer\s+[A-Za-z0-9._~+/-]{20,}/i,
  },
  {
    id: "SEC-HARDCODED-CRED",
    severity: "HIGH",
    message: "Hardcoded credential assignment",
    regex: /\b(?:password|passwd|secret|api_key|apikey|auth_token|access_token)\s*[:=]\s*["'][^"'\s]{8,}["']/i,
  },
  // --- dangerous code (Python) -----------------------------------------
  { id: "PY-EVAL", severity: "HIGH", message: "eval()/exec() — arbitrary code execution risk", regex: /\b(?:eval|exec)\s*\(/ },
  {
    id: "PY-PICKLE",
    severity: "HIGH",
    message: "pickle.loads on untrusted data is code execution",
    regex: /\bpickle\.loads?\s*\(/,
  },
  {
    id: "PY-YAML-LOAD",
    severity: "MEDIUM",
    message: "yaml.load without SafeLoader",
    regex: /\byaml\.load\s*\((?![^)]*SafeLoader)/,
  },
  {
    id: "PY-SHELL-TRUE",
    severity: "MEDIUM",
    message: "subprocess with shell=True — injection risk if input is dynamic",
    regex: /\bshell\s*=\s*True\b/,
  },
  { id: "PY-OS-SYSTEM", severity: "MEDIUM", message: "os.system — prefer subprocess without a shell", regex: /\bos\.system\s*\(/ },
  {
    id: "PY-SQL-FSTRING",
    severity: "HIGH",
    message: "SQL built with f-string — use parameterized queries",
    regex: /\b(?:execute|executemany)\s*\(\s*f["']/,
  },
  {
    id: "PY-VERIFY-FALSE",
    severity: "HIGH",
    message: "TLS verification disabled (verify=False)",
    regex: /\bverify\s*=\s*False\b/,
  },
  {
    id: "PY-MD5-PASSWORD",
    severity: "MEDIUM",
    message: "MD5/SHA1 are not password hashes — use bcrypt/argon2",
    regex: /\bhashlib\.(?:md5|sha1)\s*\([^)]*passw/i,
  },
  {
    id: "PY-FLASK-DEBUG",
    severity: "MEDIUM",
    message: "Flask debug mode in code — remote code execution if deployed",
    regex: /\.run\s*\([^)]*debug\s*=\s*True/,
  },
  {
    id: "PY-DJANGO-DEBUG",
    severity: "MEDIUM",
    message: "DEBUG = True — never deploy with debug enabled",
    regex: /^\s*DEBUG\s*=\s*True\b/,
  },
  {
    id: "PY-WEAK-CIPHER",
    severity: "HIGH",
    message: "Weak cipher/mode (DES or ECB)",
    regex: /\bMODE_ECB\b|\bDES\.new\s*\(|algorithms\.(?:TripleDES|Blowfish|ARC4)\b/,
  },
  {
    id: "PY-INSECURE-RANDOM",
    severity: "HIGH",
    message: "random module used for a secret — use the secrets module",
    regex: /\b(?:token|secret|otp|nonce|session_key)\w*\s*=\s*.*\brandom\.(?:random|randint|choice|randrange|getrandbits)\b/i,
  },
  {
    id: "PY-MKTEMP",
    severity: "MEDIUM",
    message: "tempfile.mktemp is race-prone — use mkstemp/NamedTemporaryFile",
    regex: /\btempfile\.mktemp\s*\(/,
  },
  {
    id: "PY-REQUEST-OPEN",
    severity: "MEDIUM",
    message: "File path taken from request input — path traversal risk",
    regex: /\b(?:open|send_file)\s*\([^)]*request\./,
  },
  {
    id: "GO-SHELL-EXEC",
    severity: "MEDIUM",
    message: "Shell exec with -c — injection risk if input is dynamic",
    regex: /exec\.Command\(\s*["'](?:sh|bash)["']\s*,\s*["']-c["']/,
  },
  {
    id: "PHP-DANGEROUS-EXEC",
    severity: "HIGH",
    message: "Dynamic code/command execution on a variable",
    regex: /\b(?:eval|system|shell_exec|passthru|popen)\s*\(\s*\$/,
  },
  {
    id: "NET-PLAIN-HTTP",
    severity: "MEDIUM",
    message: "Unencrypted http:// endpoint — use https",
    regex: /["']http:\/\/(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\{)[^"'\s]+["']/,
  },
  // --- dangerous code (JS/TS) ------------------------------------------
  { id: "JS-EVAL", severity: "HIGH", message: "eval()/new Function() — arbitrary code execution risk", regex: /\bnew\s+Function\s*\(/ },
  {
    id: "JS-CHILD-EXEC",
    severity: "MEDIUM",
    message: "child_process.exec with dynamic input — injection risk",
    regex: /\bchild_process\b.*\bexec\s*\(|\brequire\(['"]child_process['"]\)/,
  },
  {
    id: "JS-INNERHTML",
    severity: "MEDIUM",
    message: "innerHTML/dangerouslySetInnerHTML — XSS risk",
    regex: /\.innerHTML\s*=|dangerouslySetInnerHTML/,
  },
  // --- insecure config ---------------------------------------------------
  {
    id: "CFG-CORS-WILDCARD",
    severity: "MEDIUM",
    message: "CORS allows any origin",
    regex: /Access-Control-Allow-Origin['"]?\s*[:=,]\s*['"]\*/,
  },
  {
    id: "CFG-JWT-NONE",
    severity: "HIGH",
    message: "JWT signature verification weakened",
    regex: /algorithms?\s*[:=]\s*\[?\s*['"]none['"]|verify_signature['"]?\s*:\s*False/,
  },
  {
    id: "CFG-BIND-ALL-DEBUG",
    severity: "MEDIUM",
    message: "Service bound to 0.0.0.0 — make sure that's intended",
    regex: /['"]0\.0\.0\.0['"]/,
  },
];

const SEVERITY_ORDER: Record<Severity, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2 };

// File types worth scanning.
const SCAN_SUFFIXES = new Set([
  ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rb", ".php",
  ".java", ".kt", ".rs", ".c", ".cc", ".cpp", ".h", ".cs", ".swift", ".sh",
  ".bash", ".zsh", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf",
  ".env", ".tf", ".sql", ".html", ".vue", ".svelte",
]);

// Lines that look like test fixtures / examples get downgraded, not dropped.
const FIXTURE_HINT = /example|sample|dummy|fake|test|xxx+|placeholder|your[_-]?key/i;

// Generated/vendored files that produce only noise.
const SKIP_FILENAMES = new Set(["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "composer.lock"]);
const SKIP_NAME_PARTS = [".min.", ".map", ".bundle."];

// --- entropy-based generic secret detection -------------------------------

const ENTROPY_CANDIDATE = /["']([A-Za-z0-9+/=_-]{24,})["']/g;
const ENTROPY_CONTEXT = /\b\w*(?:key|token|secret|passw|credential|auth)\w*\s*[:=]/i;
const ENTROPY_THRESHOLD = 4.4; // bits/char; random base64 ≈ 6, English text ≈ 3–4

const SPECIFIC_SECRET_RULES = new Set([
  "SEC-AWS-KEY",
  "SEC-GITHUB-TOKEN",
  "SEC-SLACK-TOKEN",
  "SEC-API-PROVIDER-KEY",
  "SEC-STRIPE-KEY",
  "SEC-GOOGLE-KEY",
  "SEC-TELEGRAM-TOKEN",
  "SEC-HARDCODED-CRED",
  "SEC-BEARER-TOKEN",
]);

export function shannonEntropy(s: string): number {
  if (s.length === 0) {
    return 0;
  }
  const counts = new Map<string, number>();
  for (const ch of s) {
    counts.set(ch, (counts.get(ch) ?? 0) + 1);
  }
  const total = s.length;
  let entropy = 0;
  for (const n of counts.values()) {
    const p = n / total;
    entropy -= p * Math.log2(p);
  }
  return entropy;
}

function entropyFindings(line: string, lineno: number, relPath: string): Finding[] {
  if (!ENTROPY_CONTEXT.test(line)) {
    return [];
  }
  const out: Finding[] = [];
  for (const match of line.matchAll(ENTROPY_CANDIDATE)) {
    const value = match[1] ?? "";
    if (shannonEntropy(value) < ENTROPY_THRESHOLD) {
      continue;
    }
    const sev: Severity = FIXTURE_HINT.test(line) ? "MEDIUM" : "HIGH";
    out.push({
      rule: "SEC-HIGH-ENTROPY",
      severity: sev,
      message: "High-entropy string assigned to a secret-looking name",
      path: relPath,
      line: lineno,
      snippet: line.trim().slice(0, 160),
    });
  }
  return out;
}

export function scanText(text: string, relPath: string): Finding[] {
  const findings: Finding[] = [];
  const lines = text.split(/\r\n|\r|\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";
    if (line.length > 2000) {
      continue; // minified bundles
    }
    const matchedRules = new Set<string>();
    for (const rule of RULES) {
      if (rule.regex.test(line)) {
        matchedRules.add(rule.id);
        const sev: Severity = rule.severity === "CRITICAL" && FIXTURE_HINT.test(line) ? "MEDIUM" : rule.severity;
        findings.push({
          rule: rule.id,
          severity: sev,
          message: rule.message,
          path: relPath,
          line: i + 1,
          snippet: line.trim().slice(0, 160),
        });
      }
    }
    // Entropy check only when no specific secret rule already fired.
    if (![...matchedRules].some((r) => SPECIFIC_SECRET_RULES.has(r))) {
      findings.push(...entropyFindings(line, i + 1, relPath));
    }
  }
  return findings;
}

export function scanWorkspace(ws: Workspace, subpath = "."): Finding[] {
  const root = ws.resolve(subpath);
  const rootStat = fs.statSync(root);
  const files = rootStat.isFile() ? [root] : walkFiles(root, 50_000).sort();
  const findings: Finding[] = [];
  for (const p of files) {
    let stat: fs.Stats;
    try {
      stat = fs.statSync(p);
    } catch {
      continue;
    }
    if (!stat.isFile()) {
      continue;
    }
    const rel = path.relative(ws.root, p);
    const relParts = rel.split(path.sep);
    if (relParts.some((part) => SKIP_DIRS.has(part))) {
      continue;
    }
    const name = path.basename(p);
    if (SKIP_FILENAMES.has(name) || SKIP_NAME_PARTS.some((part) => name.includes(part))) {
      continue;
    }
    const ext = path.extname(p).toLowerCase();
    if (!SCAN_SUFFIXES.has(ext) && name !== ".env") {
      continue;
    }
    if (stat.size > MAX_FILE_BYTES) {
      continue;
    }
    let text: string;
    try {
      text = fs.readFileSync(p, "utf-8");
    } catch {
      continue;
    }
    findings.push(...scanText(text, rel.split(path.sep).join("/")));
    if (findings.length >= MAX_FINDINGS) {
      break;
    }
  }
  findings.sort((a, b) => {
    const sevDiff = (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9);
    if (sevDiff !== 0) {
      return sevDiff;
    }
    if (a.path !== b.path) {
      return a.path < b.path ? -1 : 1;
    }
    return a.line - b.line;
  });
  return findings.slice(0, MAX_FINDINGS);
}

export function formatFindings(findings: Finding[]): string {
  if (findings.length === 0) {
    return "No security findings. Scanned for secrets, dangerous code patterns and insecure config.";
  }
  const lines = [`${findings.length} security finding(s):`, ""];
  for (const f of findings) {
    lines.push(`[${f.severity}] ${f.rule} ${f.path}:${f.line} — ${f.message}`);
    lines.push(`    ${f.snippet}`);
  }
  const counts: Partial<Record<Severity, number>> = {};
  for (const f of findings) {
    counts[f.severity] = (counts[f.severity] ?? 0) + 1;
  }
  const summary = (Object.entries(counts) as [Severity, number][])
    .sort((a, b) => SEVERITY_ORDER[a[0]] - SEVERITY_ORDER[b[0]])
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");
  lines.push("", `Summary: ${summary}`);
  return lines.join("\n");
}
