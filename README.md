# agent-think-ledger

> **Your AI agent acts all day — but where do its judgments go to be judged?**

[![CI](https://github.com/chenhz01/agent-think-ledger/actions/workflows/ci.yml/badge.svg)](https://github.com/chenhz01/agent-think-ledger/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#quick-start)
[![Zero dependencies](https://img.shields.io/badge/dependencies-zero-green.svg)](#quick-start)

A **5-second doorbell** for agent thinking: preregister what would prove you wrong,
log your confidence, close the loop with a Brier score — all append-only, all hash-chained,
all cheap enough to never skip.

```text
OK PR-001+JD-001 on chain (115 ms) | task: migrate auth | claim: zero regression |
criteria: all 42 tests green on fresh clone | p=0.70
```

## The problem: two silent failure modes

Long-lived AI agents fail quietly in two different places:

1. **Action failure** — follow-ups never sent, monitors never restarted, inbox replies
   rotting. *(Sibling project [`agent-liveness-doctor`](https://github.com/chenhz01/agent-liveness-doctor)
   handles this: liveness probes for scheduled actions.)*
2. **Thinking failure** — judgments made on the fly, never written down, never scored,
   never audited. The agent "decided" things, but there is nothing to compare the
   decision against six weeks later. Hindsight is free to rewrite it.

We found mode 2 the hard way: a full discipline suite (15 modules — preregistration gates,
judgment journals, Feynman gates, forecast pools) sat **idle from day one**. Not because
the tools were bad — because *replies have a doorbell* (an event forces the logging step)
*and thinking doesn't*. Willpower died at the first session boundary; the ledger was even
wiped with no trace of who wiped it.

`agent-think-ledger` is the doorbell for thinking: mount it on the boot path, make the
discipline step cost ~100 ms, and make the payoff visible within a week.

## Quick start

```bash
# the doorbell: one command, two records, one chain entry (~100 ms)
python thinkledger.py quick \
  --task "migrate auth to session-store v2" \
  --claim "zero behavior regression" \
  --criteria "all 42 tests green on fresh clone" \
  --p 0.7 --deadline 2026-10-20

# ... do the work ...

# close the loop
python thinkledger.py preregister verify --id PR-001 --result PASSED
python thinkledger.py judge outcome --id JD-001 --actual 1

# the payoff, visible
python thinkledger.py report
```

`report` is the discipline dashboard — preregistrations this week, judgments this week,
kept-rate, Brier calibration (0.250 = coin-flip baseline), and hash-chain integrity.
Exit codes: `0` healthy · `1` naked (nothing registered — your thinking is running
unwatched) · `2` chain broken (P0: stop trusting every kept-rate until forensics).

## Design standard v1.0 (the six rules)

Every discipline tool we ship must satisfy all six. A tool that breaks one is a
habitat for the exact silent failure it was built to catch:

| # | Rule | Falsifiable criterion |
|---|------|----------------------|
| S1 | **Falsifiable** | a preregistration without falsification criteria is a slide, not a bet |
| S2 | **Exit-code contract** | 0/1/2; tools talk in codes, not prose |
| S3 | **Five-second doorbell** | any step > 5 s dies; quick measures its own latency in ms |
| S4 | **Doorbell, not willpower** | mount on the event path (/boot, CI); willpower dies at session boundaries |
| S5 | **Feedback ≤ 7 days** | `report` makes the payoff a number inside a week, not a vibe |
| S6 | **Append-only** | tamper a middle record → chain breaks; the judge cannot be bribed quietly |

## Commands

| command | what it does |
|---------|-------------|
| `quick` | preregister + judgment in one shot (~100 ms), hash-chained |
| `preregister add/verify/list` | nail the falsification criteria before starting; verify honestly after |
| `judge decide/outcome/list` | confidence + Brier calibration; backfill within 48 h |
| `report [--days N]` | the discipline dashboard (S5) |
| `verify` | recompute the whole hash chain |

Data lives in `--data DIR` (default `~/.think-ledger`, override via `THINKLEDGER_HOME`).
Mount suggestion for agents: run `thinkledger report` in your boot check — exit `1`
means the doorbell hasn't rung this week, exit `2` means P0 forensics first.

## Why hash-chained?

Because a judgment ledger you can quietly edit is worthless — the same agent that made
the call could rewrite it. `chain.jsonl` is one JSON object per line, each carrying
`prev` + `hash = sha256(prev|payload)[:16]`. Rewriting any **middle** record or inserting
one breaks the recomputation; `verify` exits `2` and says where.

## Honest limits

- **Tail truncation is not detectable by the chain alone.** A hash chain mathematically
  catches middle tampering and insertion, but deleting the *last* N records leaves a
  valid shorter chain. Mitigation: pin the last hash externally — CI badge, a commit
  message, another machine. (We first wrote this test expecting deletion to break the
  chain; the test taught us the boundary, so we ship the boundary in writing.)
- **No daemon, no scheduler.** This is a doorbell, not a guard: pair it with a boot-time
  check (S4) or a liveness monitor like `agent-liveness-doctor`.
- **Fixed UTC.** All timestamps render in UTC, identical on every machine — a sibling
  repo's first CI run caught a local-timezone bug of exactly this kind.
- **stdlib only, single file.** No daemon, no lockfile drama, Python 3.9+.

## Collaboration

Found a boundary case, a sharper falsification rule, or a mounting pattern that survived
production? Open an issue or PR — the six-rule standard above is the review lens.

- Email: **hcac4735@agent.qq.com** (primary) · shanlun2029@outlook.com (backup)
- Sibling projects: [agent-liveness-doctor](https://github.com/chenhz01/agent-liveness-doctor)
  (action liveness) · [skill-clinic](https://github.com/chenhz01/skill-clinic) (skill quality gate)

## License

MIT — see [LICENSE](LICENSE).
