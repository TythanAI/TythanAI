#!/usr/bin/env python3
"""
TON upstream watcher.

Polls every in-scope TON bug-bounty repository for new commits, downloads the
changed source files, runs the TythanAI community scanner over them, and pushes
a Telegram alert with the diff summary and any SAST findings.

State (last-seen commit per repo/branch) lives in monitor/state.json and is
committed back by the workflow, so the watcher never re-alerts on the same
commit and never misses a gap between runs.

No Claude / API key required: this is a standalone first-pass that keeps running
on GitHub Actions regardless of any subscription. Bring the interesting hits to
a Claude session for deep triage.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import requests

# --------------------------------------------------------------------------- #
# Scope: the official TON bug-bounty in-scope repositories.
# branch "DEFAULT" is resolved to the repo's default branch at runtime so we
# never 404 on a master/main mismatch. ton-blockchain/ton also gets testnet,
# which the bounty explicitly accepts.
#
# ton-blockchain/bug-bounty is the canonical scope definition itself: watching
# it means any change to rewards/rules — and crucially any newly added in-scope
# repo — pings you. discover_scope_repos() below also parses its README and
# alerts when the program lists a repo this monitor is not yet watching, so the
# hard-coded list below can never silently fall behind the program.
# --------------------------------------------------------------------------- #
REPOS: list[dict] = [
    {"owner": "ton-blockchain", "repo": "ton",                "branches": ["DEFAULT", "testnet"]},
    {"owner": "toncenter",      "repo": "ton-indexer",        "branches": ["DEFAULT"]},
    {"owner": "toncenter",      "repo": "ton-http-api",       "branches": ["DEFAULT"]},
    {"owner": "toncenter",      "repo": "pytonlib",           "branches": ["DEFAULT"]},
    {"owner": "ton-blockchain", "repo": "mytonctrl",          "branches": ["DEFAULT"]},
    {"owner": "ton-blockchain", "repo": "token-contract",     "branches": ["DEFAULT"]},
    {"owner": "ton-blockchain", "repo": "multisig-contract",  "branches": ["DEFAULT"]},
    {"owner": "ton-blockchain", "repo": "nominator-pool",     "branches": ["DEFAULT"]},
    {"owner": "ton-blockchain", "repo": "dns-contract",       "branches": ["DEFAULT"]},
    {"owner": "ton-blockchain", "repo": "wallet-contract",    "branches": ["DEFAULT"]},
    {"owner": "ton-blockchain", "repo": "bug-bounty",         "branches": ["DEFAULT"]},
]

# Owners whose repos count as bug-bounty scope when referenced in the program
# README (used by discover_scope_repos for the scope-drift check).
SCOPE_OWNERS = {"ton-blockchain", "toncenter"}

# TON repos that appear in the bug-bounty README but are intentionally NOT
# watched: explicitly out of scope per the program (the bridges, the explorer)
# or the program description itself. Listing them here keeps the scope-drift
# detector from false-alerting on known exclusions.
SCOPE_IGNORE = {
    "ton-blockchain/bug-bounty",             # the program description itself
    "ton-blockchain/bridge-solidity",        # TON-ETH / TON-BSC bridge — OUT of scope
    "ton-blockchain/token-bridge-solidity",  # TON-ETH token bridge     — OUT of scope
    "ton-blockchain/bridge",                 # bridge frontend          — OUT of scope
    "ton-blockchain/ton-explorer",           # blockchain explorer      — OUT of scope
}

# Source extensions worth feeding to the scanner.
SCANNABLE = {
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh",          # C/C++ core
    ".go",                                                       # indexer
    ".py",                                                       # http-api / pytonlib / mytonctrl
    ".fc", ".func", ".tolk", ".fift", ".fif",                   # contracts
    ".ts", ".js",                                               # misc tooling
}

# Security-relevant diff signal (ported from watch.sh): added/removed lines that
# touch verification / auth / parsing / crash-prone spots. A hit here is the
# primary lead for a TON bounty — fail-open guard, skipped signature check,
# ignored verify result, or a crash on attacker-controlled input — and is shown
# at the top of the alert. Covers both the C++ core and FunC/Tolk contract idioms.
SECURITY_PAT = re.compile(
    r"check_signature|signature|verify|eligible|Forbidden|Allowed|rate[_ ]?limit|"
    r"RateLimiter|skip_check|accept_message|deserialize|fetch_tl|->check\(|\.check\(|"
    r"\.ensure\(|CHECK\(|is_error\(\)|move_as_ok|Certificate|public_key|pubkey|"
    r"throw_unless|throw_if|set_code|recv_external|recv_internal|raw_reserve|"
    r"send_raw_message|set_data|seqno"
)

MAX_FILES_PER_COMMIT = 80          # cap downloads on huge merges
MAX_FILE_BYTES = 1_500_000         # skip generated/huge blobs
SCAN_TIMEOUT = 600                 # seconds per scan invocation
TG_LIMIT = 3900                    # Telegram hard cap is 4096; leave headroom

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = Path(__file__).resolve().parent / "state.json"
CLI = ROOT / "tythanai_community_cli.py"

GITHUB_API = "https://api.github.com"
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/vnd.github+json",
                        "User-Agent": "tythanai-ton-monitor"})
if GH_TOKEN:
    SESSION.headers["Authorization"] = f"Bearer {GH_TOKEN}"


# --------------------------------------------------------------------------- #
# Small HTTP helpers with retry/backoff.
# --------------------------------------------------------------------------- #
def _get(url: str, *, raw: bool = False, params: dict | None = None):
    last = None
    for attempt in range(4):
        try:
            headers = {"Accept": "application/vnd.github.raw"} if raw else {}
            r = SESSION.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code in (403, 429) and "rate limit" in r.text.lower():
                reset = int(r.headers.get("X-RateLimit-Reset", "0"))
                wait = max(5, min(60, reset - int(time.time()))) if reset else 5 * (attempt + 1)
                time.sleep(wait)
                continue
            if 400 <= r.status_code < 500:                  # auth/forbidden/policy: not retriable
                print(f"  ! {r.status_code} on {url} (not retrying)", file=sys.stderr)
                return None
            if r.status_code >= 500:                        # transient server error: retry
                time.sleep(2 ** attempt)
                continue
            return r
        except requests.RequestException as exc:           # network blip: retry
            last = exc
            time.sleep(2 ** attempt)
    print(f"  ! giving up on {url}: {last}", file=sys.stderr)
    return None


def default_branch(owner: str, repo: str) -> str | None:
    r = _get(f"{GITHUB_API}/repos/{owner}/{repo}")
    return r.json().get("default_branch") if r else None


def head_commit(owner: str, repo: str, branch: str) -> dict | None:
    r = _get(f"{GITHUB_API}/repos/{owner}/{repo}/commits/{quote(branch)}")
    if not r:
        return None
    d = r.json()
    commit = d.get("commit", {})
    return {
        "sha": d.get("sha", ""),
        "message": (commit.get("message") or "").splitlines()[0] if commit.get("message") else "",
        "author": (commit.get("author") or {}).get("name", "?"),
        "date": (commit.get("author") or {}).get("date", ""),
        "url": d.get("html_url", ""),
    }


def compare(owner: str, repo: str, base: str, head: str) -> dict | None:
    r = _get(f"{GITHUB_API}/repos/{owner}/{repo}/compare/{base}...{head}")
    return r.json() if r else None


_HUNK_HDR = re.compile(r"^@@ .*?\+(\d+)")


def security_hunks(files: list[dict]) -> list[dict]:
    """Scan the compare patches for security-relevant added/removed lines.

    This is the watch.sh signal brought into the monitor: it reads the unified
    diff GitHub already returns (no extra downloads) and surfaces the exact +/-
    lines matching SECURITY_PAT, with the new-file line number for additions.
    Returns [{file, line, sign, text}], newest-severity-first by nature of order.
    """
    out: list[dict] = []
    for f in files:
        name = f.get("filename", "")
        if Path(name).suffix.lower() not in SCANNABLE:
            continue
        patch = f.get("patch")
        if not patch:                       # binary/huge files have no patch
            continue
        new_ln = 0
        for raw in patch.splitlines():
            if raw.startswith("@@"):
                m = _HUNK_HDR.match(raw)
                new_ln = int(m.group(1)) if m else 0
                continue
            if raw.startswith(("+++", "---")):
                continue
            if raw.startswith("+"):
                body = raw[1:]
                if SECURITY_PAT.search(body):
                    out.append({"file": name, "line": new_ln, "sign": "+",
                                "text": body.strip()[:140]})
                new_ln += 1
            elif raw.startswith("-"):
                body = raw[1:]
                if SECURITY_PAT.search(body):
                    out.append({"file": name, "line": new_ln, "sign": "-",
                                "text": body.strip()[:140]})
                # removed line: new-file line number does not advance
            else:
                new_ln += 1
            if len(out) >= 40:              # cap; Telegram has a hard size limit
                return out
    return out


_GH_REPO_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def discover_scope_repos() -> set[str] | None:
    """Parse the canonical bug-bounty README and return the set of in-scope
    'owner/repo' under known TON orgs. Returns None on fetch failure so the
    caller skips the scope-drift check silently rather than crashing the run."""
    r = _get(f"{GITHUB_API}/repos/ton-blockchain/bug-bounty/readme", raw=True)
    if not r:
        return None
    found: set[str] = set()
    for owner, repo in _GH_REPO_RE.findall(r.text):
        repo = repo.removesuffix(".git")
        if owner.lower() in SCOPE_OWNERS:
            found.add(f"{owner}/{repo}")
    return found


# --------------------------------------------------------------------------- #
# Scanning.
# --------------------------------------------------------------------------- #
def download_changed_files(owner: str, repo: str, files: list[dict], dest: Path) -> list[str]:
    """Write new-version contents of changed source files into dest. Returns names."""
    written = []
    for f in files[:MAX_FILES_PER_COMMIT]:
        name = f.get("filename", "")
        if f.get("status") == "removed":
            continue
        if Path(name).suffix.lower() not in SCANNABLE:
            continue
        raw_url = f.get("raw_url") or f.get("contents_url")
        if not raw_url:
            continue
        r = _get(raw_url, raw=True)
        if not r:
            continue
        content = r.content
        if len(content) > MAX_FILE_BYTES:
            continue
        out = dest / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        written.append(name)
    return written


def run_scanner(scan_dir: Path) -> dict:
    """Invoke the community CLI; return parsed JSON (or empty result on failure)."""
    out_json = scan_dir.parent / "findings.json"
    try:
        proc = subprocess.run(
            [sys.executable, str(CLI), "scan", str(scan_dir),
             "--json", str(out_json), "--quiet", "--no-sca", "--no-secrets", "--no-iac"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=SCAN_TIMEOUT,
        )
        if out_json.exists():
            return json.loads(out_json.read_text())
        print(f"  ! scanner produced no json (rc={proc.returncode}): "
              f"{proc.stderr[-300:]}", file=sys.stderr)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        print(f"  ! scanner error: {exc}", file=sys.stderr)
    return {"total": 0, "findings": [], "by_severity": {}}


# --------------------------------------------------------------------------- #
# Telegram.
# --------------------------------------------------------------------------- #
def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_telegram(text: str) -> None:
    if not (TG_TOKEN and TG_CHAT):
        # No secrets configured yet: surface to the Actions job summary instead.
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(text.replace("<b>", "**").replace("</b>", "**")
                         .replace("<code>", "`").replace("</code>", "`") + "\n\n---\n\n")
        print("  (no Telegram secrets; wrote alert to job summary)")
        return
    api = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    for chunk_start in range(0, len(text), TG_LIMIT):
        chunk = text[chunk_start:chunk_start + TG_LIMIT]
        for attempt in range(4):
            try:
                resp = requests.post(api, timeout=30, data={
                    "chat_id": TG_CHAT, "text": chunk,
                    "parse_mode": "HTML", "disable_web_page_preview": "true"})
                if resp.status_code == 200:
                    break
                print(f"  ! telegram {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
                time.sleep(2 ** attempt)
            except requests.RequestException as exc:
                print(f"  ! telegram net error: {exc}", file=sys.stderr)
                time.sleep(2 ** attempt)


SEV_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}
SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def build_alert(owner, repo, branch, commit, files, scanned, result,
                hunks=None, commits=None) -> str:
    findings = result.get("findings", []) or []
    hunks = hunks or []
    commits = commits or []
    by_sev: dict[str, int] = {}
    for f in findings:
        sev = (f.get("severity") or "INFO").upper()
        by_sev[sev] = by_sev.get(sev, 0) + 1

    # A security-relevant diff hit is, for TON, as actionable as a SAST CRITICAL.
    actionable = sum(by_sev.get(s, 0) for s in ("CRITICAL", "HIGH")) or bool(hunks)
    head = "🚨" if actionable else "🔔"
    lines = [f"{head} <b>{_esc(owner)}/{_esc(repo)}</b> @ <code>{_esc(branch)}</code>",
             "",
             f"<b>{_esc(commit['message'])}</b>",
             f"<code>{commit['sha'][:10]}</code> · {_esc(commit['author'])} · {_esc(commit['date'][:10])}",
             commit["url"], ""]

    # If several commits landed between runs, list their subjects so a
    # security-relevant one is never hidden behind the HEAD subject.
    if len(commits) > 1:
        lines.append(f"🧩 {len(commits)} commits in range:")
        for sub in commits[-8:]:
            lines.append(f"   • {_esc(sub[:90])}")
        if len(commits) > 8:
            lines.append(f"   … +{len(commits) - 8} earlier")
        lines.append("")

    code_files = [f for f in files if Path(f).suffix.lower() in SCANNABLE]
    lines.append(f"📄 {len(files)} files changed ({len(code_files)} code, {len(scanned)} scanned)")
    for name in code_files[:12]:
        lines.append(f"   • <code>{_esc(name)}</code>")
    if len(code_files) > 12:
        lines.append(f"   … +{len(code_files) - 12} more")
    lines.append("")

    # Primary lead: security-relevant diff lines (audit these first).
    if hunks:
        lines.append(f"🔑 <b>{len(hunks)} security-relevant diff line(s)</b> — audit first:")
        for h in hunks[:12]:
            lines.append(f"   <code>{_esc(h['file'])}:{h['line']}</code>")
            lines.append(f"   <code>{_esc(h['sign'])} {_esc(h['text'])}</code>")
        if len(hunks) > 12:
            lines.append(f"   … +{len(hunks) - 12} more")
        lines.append("")

    if findings:
        summary = "  ".join(f"{SEV_ICON.get(s,'')}{s[:4]} {by_sev[s]}"
                            for s in SEV_ORDER if by_sev.get(s))
        lines.append(f"🔎 <b>SAST: {len(findings)} findings</b>  {summary}")
        # Show the most severe findings first.
        ranked = sorted(findings, key=lambda f: SEV_ORDER.index((f.get("severity") or "INFO").upper())
                        if (f.get("severity") or "INFO").upper() in SEV_ORDER else 99)
        for f in ranked[:8]:
            sev = (f.get("severity") or "INFO").upper()
            rid = f.get("id") or f.get("rule_id") or "?"
            loc = f"{f.get('file','?')}:{f.get('line','?')}"
            msg = (f.get("message") or f.get("description") or "")[:140]
            lines.append(f"{SEV_ICON.get(sev,'')} <b>{_esc(sev)}</b> <code>{_esc(str(rid))}</code>")
            lines.append(f"   {_esc(loc)}")
            if msg:
                lines.append(f"   {_esc(msg)}")
        if len(findings) > 8:
            lines.append(f"   … +{len(findings) - 8} more findings")
    else:
        lines.append("🔎 SAST: no findings on the diff (commit still worth a glance).")

    if actionable:
        lines.append("")
        lines.append("➡️ <i>Actionable — bring to a Claude session for deep triage.</i>")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Main.
# --------------------------------------------------------------------------- #
def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def main() -> int:
    if not GH_TOKEN:
        print("WARNING: no GITHUB_TOKEN; API rate limits will be tight.", file=sys.stderr)

    # Manual wiring check: `workflow_dispatch` with test_telegram=true sends a ping
    # immediately, regardless of baseline state, so you can confirm Telegram works
    # without waiting for a real upstream commit.
    if os.environ.get("TEST_TELEGRAM", "").strip().lower() in ("1", "true", "yes", "on"):
        send_telegram("🧪 <b>TON monitor — test ping.</b>\n"
                      "If you can read this, your Telegram wiring is correct. "
                      "Real alerts will arrive automatically on the next upstream commit.")
        print("test ping sent")

    state = load_state()
    first_run = not state
    alerts = 0
    changed_state = False

    for entry in REPOS:
        owner, repo = entry["owner"], entry["repo"]
        branches = []
        for b in entry["branches"]:
            branches.append(default_branch(owner, repo) if b == "DEFAULT" else b)
        for branch in dict.fromkeys(filter(None, branches)):   # dedupe, drop None
            key = f"{owner}/{repo}@{branch}"
            commit = head_commit(owner, repo, branch)
            if not commit or not commit["sha"]:
                print(f"  - {key}: unreachable, skipping")
                continue
            prev = state.get(key)
            if prev == commit["sha"]:
                print(f"  = {key}: up to date ({commit['sha'][:10]})")
                continue

            print(f"  + {key}: {('baseline' if not prev else prev[:10]+'..')}{commit['sha'][:10]}")
            state[key] = commit["sha"]
            changed_state = True

            if not prev:
                continue  # establish baseline silently; don't alert on first sight

            cmp = compare(owner, repo, prev, commit["sha"])
            files = (cmp or {}).get("files", []) or []
            filenames = [f.get("filename", "") for f in files]
            commit_subjects = [
                (c.get("commit", {}).get("message") or "").splitlines()[0]
                for c in (cmp or {}).get("commits", []) or []
                if (c.get("commit", {}).get("message") or "").strip()
            ]
            hunks = security_hunks(files)        # watch.sh-style security diff lines

            scanned: list[str] = []
            result = {"total": 0, "findings": [], "by_severity": {}}
            with tempfile.TemporaryDirectory(prefix="ton_mon_") as tmp:
                scan_dir = Path(tmp) / "src"
                scan_dir.mkdir(parents=True, exist_ok=True)
                scanned = download_changed_files(owner, repo, files, scan_dir)
                if scanned:
                    result = run_scanner(scan_dir)

            send_telegram(build_alert(owner, repo, branch, commit, filenames,
                                      scanned, result, hunks, commit_subjects))
            alerts += 1

    # ---- scope drift: tell me when the program lists a repo I don't watch ----
    # Cross-checks the canonical bug-bounty README so the hard-coded REPOS list
    # can never silently fall behind a newly added in-scope repo. Alerts only
    # when the set of unmonitored in-scope repos *changes* (no per-run spam).
    discovered = discover_scope_repos()
    if discovered is not None:
        monitored = {f"{e['owner']}/{e['repo']}" for e in REPOS}
        unmonitored = sorted(discovered - monitored - SCOPE_IGNORE)
        if unmonitored != state.get("__scope_unmonitored__"):
            state["__scope_unmonitored__"] = unmonitored
            changed_state = True
            if not first_run and unmonitored:
                msg = ["⚠️ <b>TON bug-bounty scope changed</b>", "",
                       "In-scope repo(s) this monitor is NOT watching yet:"]
                for rr in unmonitored:
                    msg.append(f"   • <code>{_esc(rr)}</code>  https://github.com/{rr}")
                msg += ["", "➡️ <i>Add them to REPOS in monitor/ton_monitor.py.</i>"]
                send_telegram("\n".join(msg))
                alerts += 1

    if changed_state:
        save_state(state)

    if first_run:
        msg = (f"✅ <b>TON monitor armed.</b> Baselined {len(state)} repo/branch refs. "
               f"You'll get an alert on the next upstream commit to any of them.")
        send_telegram(msg)
        print(msg)

    print(f"Done. {alerts} alert(s); state {'updated' if changed_state else 'unchanged'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
