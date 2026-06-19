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

Edit the `REPOS` list in `ton_monitor.py` to add or remove targets.

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
- First time a ref is seen it is baselined **silently** (no alert) so activation
  doesn't dump a wall of history.

## Tuning

- **Frequency:** edit the `cron:` in `.github/workflows/ton-monitor.yml`
  (`*/30 * * * *` = every 30 min; scheduled runs may be delayed by GitHub under
  load — normal).
- **Noise:** the alert header is 🚨 when there are CRITICAL/HIGH findings, 🔔
  otherwise. Every new commit is reported (even with zero findings) so nothing
  upstream slips by — tighten in `build_alert` if you want findings-only.
- **Scope of scan:** `--no-sca --no-secrets --no-iac` keeps it to SAST + the
  smart-contract audit on the diff; drop those flags in `run_scanner` to widen.
