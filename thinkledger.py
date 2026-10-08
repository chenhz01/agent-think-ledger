#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
thinkledger — a 5-second doorbell for agent thinking.

Two silent failure modes kill long-lived AI agents:
  1. ACTION failure — follow-ups never sent, monitors never run. (see: agent-liveness-doctor)
  2. THINKING failure — judgments never preregistered, never scored, never audited.

thinkledger is the doorbell for mode 2. Before starting real work you nail down
what would prove you wrong (preregister) and how confident you are (judgment),
append-only, hash-chained, cheap enough to never skip.

Design standard v1.0 (six rules):
  S1 Falsifiable  — a preregistration without falsification criteria is a slide, not a bet
  S2 Exit codes   — 0 ok / 1 gap / 2 chain broken; tools talk in codes, not prose
  S3 Five seconds — any discipline step must cost < 5s (measured: ~100ms) or it dies
  S4 Doorbell     — mount tools on the event path (/boot, CI), never on willpower
  S5 Feedback     — discipline must show a visible number within 7 days (report)
  S6 Append-only  — hash-chained history; tamper and the chain breaks

Usage:
  thinkledger [--data DIR] quick --task T --claim C --criteria K --p 0.7 [--deadline D]
  thinkledger [--data DIR] preregister add|verify|list ...
  thinkledger [--data DIR] judge decide|outcome|list ...
  thinkledger [--data DIR] report [--days 7]
  thinkledger [--data DIR] verify

Exit codes: 0 = ok, 1 = gap (e.g. nothing registered this week), 2 = chain broken.
Timestamps are rendered in fixed UTC — identical on every machine (first CI run
of a sibling repo caught a local-tz bug here; do not reintroduce it).
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

VERSION = "1.0.0"
DEFAULT_HOME = os.environ.get("THINKLEDGER_HOME") or os.path.join(
    os.path.expanduser("~"), ".think-ledger")

CHAIN = "chain.jsonl"       # append-only hash chain (one JSON object per line)
PR = "preregister.json"     # BJT-01 style preregistrations
JD = "judgment.json"        # judgment log with Brier calibration


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _paths(data):
    return (os.path.join(data, CHAIN), os.path.join(data, PR), os.path.join(data, JD))


def _ensure(data):
    os.makedirs(data, exist_ok=True)


def _load_json(path, default):
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def chain_append(chain_path, entry):
    """Append-only hash chain. prev = last line's hash; hash = sha256(prev|payload)[:16]."""
    prev = "GENESIS"
    seq = 0
    if os.path.isfile(chain_path):
        with open(chain_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    prev = json.loads(line)["hash"]
                    seq += 1
    blob = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    h = hashlib.sha256((prev + "|" + blob).encode("utf-8")).hexdigest()[:16]
    rec = {"seq": seq, "prev": prev, "payload": entry, "hash": h, "ts": utcnow()}
    with open(chain_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return h


def chain_verify(chain_path):
    """Recompute the whole chain. Returns (True, count) or (False, broken_seq)."""
    if not os.path.isfile(chain_path):
        return True, 0
    prev = "GENESIS"
    seq = -1
    with open(chain_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            seq += 1
            rec = json.loads(line)
            blob = json.dumps(rec["payload"], ensure_ascii=False, sort_keys=True)
            h = hashlib.sha256((prev + "|" + blob).encode("utf-8")).hexdigest()[:16]
            if h != rec["hash"] or rec["prev"] != prev or rec["seq"] != seq:
                return False, seq
            prev = rec["hash"]
    return True, seq + 1


# ---------------- quick: the 5-second doorbell (S3) ----------------
def cmd_quick(a, data):
    t0 = time.time()
    if not 0.0 <= a.p <= 1.0:
        print("FAIL: confidence p must be within [0,1]")
        return 1
    chain_path, pr_path, jd_path = _paths(data)
    _ensure(data)

    pr = _load_json(pr_path, [])
    pid = "PR-%03d" % (len(pr) + 1)
    pr.append({"id": pid, "task": a.task, "claim": a.claim,
               "criteria": a.criteria, "deadline": a.deadline,
               "status": "OPEN", "registered_at": utcnow()})
    _save_json(pr_path, pr)

    jd = _load_json(jd_path, [])
    jid = "JD-%03d" % (len(jd) + 1)
    jd.append({"id": jid, "q": a.task, "prediction": a.claim,
               "p": a.p, "actual": None, "at": utcnow()})
    _save_json(jd_path, jd)

    chain_append(chain_path, {"kind": "quick", "pr": pid, "jd": jid,
                              "task": a.task, "claim": a.claim,
                              "criteria": a.criteria, "p": a.p, "deadline": a.deadline})
    ms = (time.time() - t0) * 1000
    print("OK %s+%s on chain (%.0f ms) | task: %s | claim: %s | criteria: %s | p=%.2f"
          % (pid, jid, ms, a.task, a.claim, a.criteria, a.p))
    return 0


# ---------------- preregister ----------------
def cmd_pr_add(a, data):
    chain_path, pr_path, _ = _paths(data)
    _ensure(data)
    pr = _load_json(pr_path, [])
    pid = "PR-%03d" % (len(pr) + 1)
    pr.append({"id": pid, "task": a.task, "claim": a.claim,
               "criteria": a.criteria, "deadline": a.deadline,
               "status": "OPEN", "registered_at": utcnow()})
    _save_json(pr_path, pr)
    chain_append(chain_path, {"kind": "preregister", "id": pid, "task": a.task,
                              "claim": a.claim, "criteria": a.criteria, "deadline": a.deadline})
    print("OK preregistered %s (criteria: %s)" % (pid, a.criteria))
    return 0


def cmd_pr_verify(a, data):
    chain_path, pr_path, _ = _paths(data)
    pr = _load_json(pr_path, [])
    for it in pr:
        if it["id"] == a.id:
            it["status"] = a.result
            it["verified_at"] = utcnow()
            _save_json(pr_path, pr)
            chain_append(chain_path, {"kind": "preregister_verify", "id": a.id, "result": a.result})
            print("OK %s -> %s" % (a.id, a.result))
            return 0
    print("FAIL: %s not found" % a.id)
    return 1


def cmd_pr_list(_a, data):
    _, pr_path, _ = _paths(data)
    pr = _load_json(pr_path, [])
    if not pr:
        print("(empty)")
        return 0
    for i in pr:
        print("%s [%s] %s | criteria: %s" % (i["id"], i["status"], i["task"], i["criteria"]))
    return 0


# ---------------- judgment (Brier calibration) ----------------
def _brier(p, o):
    return (p - o) ** 2


def cmd_jd_decide(a, data):
    chain_path, _, jd_path = _paths(data)
    _ensure(data)
    if not 0.0 <= a.p <= 1.0:
        print("FAIL: confidence p must be within [0,1]")
        return 1
    jd = _load_json(jd_path, [])
    jid = "JD-%03d" % (len(jd) + 1)
    jd.append({"id": jid, "q": a.q, "prediction": a.prediction,
               "p": a.p, "actual": None, "at": utcnow()})
    _save_json(jd_path, jd)
    chain_append(chain_path, {"kind": "judgment", "id": jid, "q": a.q, "p": a.p})
    print("OK judgment logged %s: p=%.2f" % (jid, a.p))
    return 0


def cmd_jd_outcome(a, data):
    chain_path, _, jd_path = _paths(data)
    jd = _load_json(jd_path, [])
    for it in jd:
        if it["id"] == a.id:
            it["actual"] = int(a.actual)
            it["outcome_at"] = utcnow()
            _save_json(jd_path, jd)
            chain_append(chain_path, {"kind": "judgment_outcome", "id": a.id, "actual": int(a.actual)})
            print("OK %s actual=%d Brier=%.3f" % (a.id, it["actual"], _brier(it["p"], it["actual"])))
            return 0
    print("FAIL: %s not found" % a.id)
    return 1


def cmd_jd_list(_a, data):
    _, _, jd_path = _paths(data)
    jd = _load_json(jd_path, [])
    if not jd:
        print("(empty)")
        return 0
    for i in jd:
        act = i["actual"] if i["actual"] is not None else "?"
        print("%s p=%.2f actual=%s | %s" % (i["id"], i["p"], act, i["q"]))
    return 0


# ---------------- report: the discipline dashboard (S5) ----------------
def cmd_report(a, data):
    chain_path, pr_path, jd_path = _paths(data)
    pr = _load_json(pr_path, [])
    jd = _load_json(jd_path, [])

    now_t = time.time()

    def within(iso, days):
        try:
            t = time.mktime(time.strptime(iso[:10], "%Y-%m-%d"))
        except (ValueError, TypeError):
            return False
        age = now_t - t
        return 0 <= age <= days * 86400

    pr_week = [i for i in pr if within(i.get("registered_at", ""), a.days)]
    jd_week = [i for i in jd if within(i.get("at", ""), a.days)]
    closed = [i for i in pr if i["status"] != "OPEN"]
    kept = [i for i in closed if i["status"] == "PASSED"]
    rate = (len(kept) / len(closed) * 100) if closed else 0.0
    done = [i for i in jd if i["actual"] is not None]
    brier = (sum(_brier(i["p"], i["actual"]) for i in done) / len(done)) if done else None

    ok, pos = chain_verify(chain_path)
    print("=" * 48)
    print("Thinking discipline dashboard · last %d day(s)" % a.days)
    print("=" * 48)
    print("preregistrations (week/total) : %d / %d" % (len(pr_week), len(pr)))
    print("judgments        (week/total) : %d / %d" % (len(jd_week), len(jd)))
    print("preregistration kept-rate    : %d/%d = %.1f%% (open %d)"
          % (len(kept), len(closed), rate, len(pr) - len(closed)))
    print("Brier calibration            : %s (0.25 = coin-flip baseline; lower is better)"
          % ("%.3f" % brier if brier is not None else "no outcomes yet"))
    print("hash chain                   : %s" % ("intact (%d)" % pos if ok else "BROKEN @%s" % pos))
    print("-" * 48)
    if not ok:
        print("P0 chain broken — the judge has been tampered with; every kept-rate is now "
              "untrustworthy. Stop logging, find who rewrote history first.")
        return 2
    if not pr_week and not jd_week:
        print("Doorbell never rang: zero preregistrations and zero judgments this week. "
              "Your thinking is running naked — start real work with `quick`.")
        return 1
    return 0


# ---------------- verify ----------------
def cmd_verify(_a, data):
    chain_path, _, _ = _paths(data)
    ok, n = chain_verify(chain_path)
    if ok:
        print("OK hash chain intact: %d record(s)" % n)
        return 0
    print("FAIL chain broken at seq=%s" % n)
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser(prog="thinkledger",
                                 description="a 5-second doorbell for agent thinking (v%s)" % VERSION)
    ap.add_argument("--data", default=DEFAULT_HOME, help="data directory (default: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("quick", help="5-second doorbell: preregister + judgment in one shot")
    q.add_argument("--task", required=True)
    q.add_argument("--claim", required=True)
    q.add_argument("--criteria", required=True, help="what evidence would prove you wrong")
    q.add_argument("--deadline", default="2099-12-31")
    q.add_argument("--p", type=float, required=True)

    pr = sub.add_parser("preregister", help="preregistration gate")
    prs = pr.add_subparsers(dest="sub", required=True)
    pa = prs.add_parser("add")
    pa.add_argument("--task", required=True)
    pa.add_argument("--claim", required=True)
    pa.add_argument("--criteria", required=True)
    pa.add_argument("--deadline", default="2099-12-31")
    pv = prs.add_parser("verify")
    pv.add_argument("--id", required=True)
    pv.add_argument("--result", required=True, choices=["PASSED", "FAILED"])
    pl = prs.add_parser("list")

    jd = sub.add_parser("judge", help="judgment log with Brier calibration")
    jds = jd.add_subparsers(dest="sub", required=True)
    jda = jds.add_parser("decide")
    jda.add_argument("--q", required=True)
    jda.add_argument("--prediction", required=True)
    jda.add_argument("--p", type=float, required=True)
    jdo = jds.add_parser("outcome")
    jdo.add_argument("--id", required=True)
    jdo.add_argument("--actual", type=int, required=True, choices=[0, 1])
    jdl = jds.add_parser("list")

    rp = sub.add_parser("report", help="thinking discipline dashboard")
    rp.add_argument("--days", type=int, default=7)

    vf = sub.add_parser("verify", help="verify hash chain integrity")

    a = ap.parse_args(argv)
    if a.cmd == "quick":
        return cmd_quick(a, a.data)
    if a.cmd == "preregister":
        return {"add": cmd_pr_add, "verify": cmd_pr_verify, "list": cmd_pr_list}[a.sub](a, a.data)
    if a.cmd == "judge":
        return {"decide": cmd_jd_decide, "outcome": cmd_jd_outcome, "list": cmd_jd_list}[a.sub](a, a.data)
    if a.cmd == "report":
        return cmd_report(a, a.data)
    if a.cmd == "verify":
        return cmd_verify(a, a.data)
    ap.error("unknown command")


if __name__ == "__main__":
    sys.exit(main())
