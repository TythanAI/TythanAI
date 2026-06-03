# Launch playbook

Ready-to-post content for launching TythanAI. Copy-paste, tweak the voice to your own, and post from your account. **Don't mass-post the same text everywhere on the same day** — space it out and engage with replies. Authentic beats spammy every time.

Recommended order: **README polish (done) → Show HN → awesome-lists → community chats → write-up.**

---

## 1. Hacker News — "Show HN"

Post at https://news.ycombinator.com/submit on a weekday morning US time (Tue–Thu, ~8–10am ET is good). Title must start with `Show HN:`.

**Title:**
```
Show HN: TythanAI – Open-source security scanner that audits TON/Solana/Solidity
```

**URL:** `https://github.com/TythanAI/TythanAI`

**First comment (post immediately after submitting):**
```
Hi HN! I built TythanAI because every security scanner I tried did either SAST
or dependencies, but none understood smart contracts — and the few that do are
single-chain and closed-source.

TythanAI runs fully local (no account, no telemetry) and combines:
- Native Web3 auditing for TON FunC/Tolk, Solana/Anchor, CosmWasm and Solidity
- Classic SAST (Semgrep + curated rules), dependency CVEs (OSV.dev + EPSS), secrets, IaC
- SARIF/JSON/HTML output, so it drops straight into CI

  pip install tythanai-community
  tythanai scan ./your-project

It's source-available (BSL 1.1). I'd love feedback on the Web3 rule coverage and
false-positive rate — happy to answer anything.
```

> Tip: reply to every comment in the first few hours. Engagement keeps you on the front page.

---

## 2. Reddit

Tailor the framing per subreddit — read each sub's self-promotion rules first.

- **r/netsec** — needs technical substance. Lead with the Web3 + SAST combo and the disclosure write-up, not "I made a tool."
- **r/ethdev**, **r/solana**, **r/CryptoTechnology** — lead with the chain you're targeting.
- **r/opensource**, **r/Python** — lead with "open-source, local, no account."

**Template:**
```
Title: Open-source security scanner with native TON/Solana/CosmWasm + Solidity auditing

I got tired of stitching together Slither + a SAST tool + a secrets scanner, so I
built one CLI that does all of it locally — no account, no telemetry.

  pip install tythanai-community
  tythanai scan ./project

It found reentrancy + a leaked AWS key in my test repo in one pass. Web3 coverage:
TON FunC/Tolk, Solana/Anchor, CosmWasm, Solidity. Plus SAST (Semgrep + curated
rules), SCA via OSV.dev, secrets and IaC.

Source-available (BSL 1.1): https://github.com/TythanAI/TythanAI
Would love feedback on rule coverage and FP rate.
```

---

## 3. X / Twitter

```
🚀 Just open-sourced TythanAI — the first free security scanner that audits
TON, Solana & CosmWasm smart contracts natively, alongside Solidity + classic
SAST/SCA/secrets/IaC.

One CLI. Runs local. No account.

  pip install tythanai-community
  tythanai scan ./project

⭐ https://github.com/TythanAI/TythanAI
```
Add a screenshot/GIF of a scan with findings — tweets with media get far more reach.
Tag/relevant hashtags: #TON #Solana #web3security #DevSecOps #infosec

---

## 4. Awesome-list pull requests (high, lasting traffic)

Open a small PR adding one bullet to each. Read each list's contribution format first.

- `analysis-tools-dev/static-analysis` (huge SAST list)
- `mre/awesome-static-analysis`
- `0xor0ne/awesome-list` (security)
- `ton-community/awesome-ton`
- `avineshwar/awesome-solana` / other awesome-solana lists
- `CosmWasm/awesome-cosmwasm`
- `sindresorhus/awesome` adjacent security lists

**Suggested entry:**
```
- [TythanAI](https://github.com/TythanAI/TythanAI) - Local, open-source scanner
  combining SAST/SCA/secrets/IaC with native TON, Solana, CosmWasm and Solidity
  smart-contract auditing.
```

---

## 5. Product Hunt

One-shot launch. Prepare: logo, 3–4 screenshots, a 30–60s demo GIF, and the tagline:
> "Open-source security scanner for Web3 + classic code. One CLI, no account."
Launch 12:01am PT; rally early upvotes from your network in the first hours.

---

## 6. The credibility piece — turn GHOST-2025-001 into a write-up

You already have `GHOST-2025-001-public-disclosure.md`. A real, responsibly-disclosed
vulnerability write-up is the single most powerful credibility asset for a security
tool. Publish it as a blog post (dev.to / Hashnode / Medium / Habr) titled around the
impact, and end with "this is the class of bug TythanAI detects automatically." Link it
from HN/Reddit. This converts far better than a feature list.

---

## Before you launch — quick checklist

- [ ] Repo has a clear social-preview image (Settings → General → Social preview)
- [ ] Repo topics set: `security`, `sast`, `web3`, `ton`, `solana`, `solidity`, `devsecops`
- [ ] README demo GIF recorded (asciinema → asciinema.org, or a terminal screen-record)
- [ ] `pip install tythanai-community` works on a clean machine (verified ✓)
- [ ] You've starred your own repo and asked 5–10 friends/colleagues to star it
      (the jump from 0 → ~25 stars is what makes a repo look alive)
- [ ] You can respond to comments for the first 3–4 hours after each post
```
