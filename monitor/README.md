# TON upstream monitor

Watches every in-scope TON bug-bounty repository for new commits, scans the diff
with the TythanAI community scanner, and sends a Telegram alert with the changed
files and any SAST findings.

It runs on **GitHub Actions** on a schedule — no PC kept on, **no Claude/API key
needed**, so it keeps working regardless of any subscription. Use it as a durable
first pass: when an alert flags an actionable (CRITICAL/HIGH) hit, bring that one
commit to a Claude session for deep triage.

## What it watches

| Repo | Branches |
|---|---|
| `ton-blockchain/ton` | default + `testnet` |
| `toncenter/ton-indexer` | default |
| `toncenter/ton-http-api` | default |
| `toncenter/pytonlib` | default |
| `ton-blockchain/mytonctrl` | default |
| `ton-blockchain/token-contract` | default |
| `ton-blockchain/multisig-contract` | default |
| `ton-blockchain/nominator-pool` | default |
| `ton-blockchain/dns-contract` | default |
| `ton-blockchain/wallet-contract` | default |
| `ton-blockchain/bug-bounty` | default |

That is every in-scope GitHub repo in the official program. Edit the `REPOS`
list in `ton_monitor.py` to add or remove targets.

**Scope can't silently drift.** The monitor also watches the program itself
(`ton-blockchain/bug-bounty`) **and** parses its README every run: if the
program ever lists an in-scope repo that isn't in `REPOS`, you get a
`⚠️ scope changed` alert telling you to add it. Repos that are intentionally
**out of scope** (the TON-ETH/BSC/token bridges, the blockchain explorer) are
listed in `SCOPE_IGNORE` so they don't false-alert — don't add them, reports
on them are rejected.

**Not covered (by design):** purely web targets in scope — `ton.org`,
`toncenter.com`, and the HackenProof *ton-society* frontend program — aren't
git repos, so a commit-watcher can't see them. Those are a separate (web) bug
class.

## Setup (≈3 minutes)

### 1. Create a Telegram bot

1. In Telegram, open **@BotFather** → `/newbot` → follow prompts → copy the
   **bot token** (looks like `123456:ABC-DEF...`).
2. Send any message to your new bot (so it can write to you).
3. Get your **chat id**: open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and read
   `result[].message.chat.id` (or message **@userinfobot**).

### 2. Add the secrets to the repo

GitHub → **Settings → Secrets and variables → Actions → New repository secret**:

- `TELEGRAM_BOT_TOKEN` — the bot token
- `TELEGRAM_CHAT_ID` — your chat id

(Without these the workflow still runs and writes the report to the Actions job
summary instead of Telegram — handy for a first test.)

### 3. Activate the schedule

GitHub only fires `schedule:` for workflows on the repository's **default
branch**. So:

- **To test now:** GitHub → **Actions → "TON upstream monitor" → Run workflow**
  (`workflow_dispatch`). The first run baselines all repos and sends a
  "monitor armed" message; no commit alerts yet.
- **To turn on the every-30-min cron:** merge this branch into the default
  branch.

## How it works

- `ton_monitor.py` asks the GitHub API for each repo/branch's latest commit.
- `monitor/state.json` stores the last-seen commit per ref. The workflow commits
  it back after every run (message tagged `[skip ci]`), so the monitor never
  re-alerts on the same commit and never misses a gap between runs.
- On a new commit it pulls the `compare` diff, downloads the new version of the
  changed source files (C/C++, Go, Python, FunC/Tolk/Fift, TS/JS), runs the
  scanner over just those files, and sends one alert.
- **Security-relevant diff lines come first.** It scans the diff itself for the
  high-signal TON bug patterns (`check_signature`, `verify`, `skip_check`,
  `move_as_ok`/`.ensure`/`CHECK(` on parsed input, `throw_unless`, `set_code`,
  …) and puts the exact `file:line` `+/-` lines at the top of the alert — the
  fastest lead to a fail-open / skipped-check / crash-on-input bug. A hit here
  promotes the alert to 🚨.
- **No commit hides behind another.** If several commits landed since the last
  run, the alert lists every commit subject in the range, so a security commit
  isn't masked by whatever happens to be HEAD.
- First time a ref is seen it is baselined **silently** (no alert) so activation
  doesn't dump a wall of history. The same is true for the scope baseline.

## Tuning

- **Frequency:** edit the `cron:` in `.github/workflows/ton-monitor.yml`
  (`*/15 * * * *` = every 15 min, to be early; scheduled runs may be delayed by
  GitHub under load — that only adds latency, never a miss, since each run diffs
  from the last-seen commit. On a private repo this uses ~2x the Actions minutes
  of `*/30`; dial back if that matters).
- **Noise:** the alert header is 🚨 when there are CRITICAL/HIGH findings, 🔔
  otherwise. Every new commit is reported (even with zero findings) so nothing
  upstream slips by — tighten in `build_alert` if you want findings-only.
- **Scope of scan:** `--no-sca --no-secrets --no-iac` keeps it to SAST + the
  smart-contract audit on the diff; drop those flags in `run_scanner` to widen.
