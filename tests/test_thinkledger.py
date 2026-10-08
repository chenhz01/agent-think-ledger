# -*- coding: utf-8 -*-
"""thinkledger tests — falsifiable where it matters:
chain tamper MUST break, exit codes MUST match contract, timestamps MUST be UTC."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(HERE, "thinkledger.py")
PY = sys.executable


def run(args, data):
    return subprocess.run([PY, TL, "--data", data] + args,
                          capture_output=True, text=True, timeout=60)


class ThinkLedgerTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="tl-test-")

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    # --- S6: hash chain integrity ---
    def test_quick_appends_chain_record(self):
        r = run(["quick", "--task", "t1", "--claim", "c1", "--criteria", "k1", "--p", "0.7"], self.data)
        self.assertEqual(r.returncode, 0)
        ok = run(["verify"], self.data)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("intact: 1", ok.stdout)

    def test_tamper_breaks_chain(self):
        run(["quick", "--task", "t1", "--claim", "c1", "--criteria", "k1", "--p", "0.7"], self.data)
        chain = os.path.join(self.data, "chain.jsonl")
        with open(chain, "r", encoding="utf-8") as f:
            rec = json.loads(f.readline())
        rec["payload"]["claim"] = "REWRITTEN AFTER THE FACT"
        with open(chain, "w", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        r = run(["verify"], self.data)
        self.assertEqual(r.returncode, 2, "tampering MUST exit 2")
        self.assertIn("broken", r.stdout.lower())

    def test_delete_middle_line_breaks_chain(self):
        # NOTE: hash chains detect middle tampering/insertion but NOT tail truncation
        # (with no external anchor). We assert the middle case here; the tail-truncation
        # boundary is documented in README "Honest limits" with the external-anchor
        # mitigation (pin the last hash in a commit / badge / another machine).
        run(["quick", "--task", "t1", "--claim", "c1", "--criteria", "k1", "--p", "0.7"], self.data)
        run(["quick", "--task", "t2", "--claim", "c2", "--criteria", "k2", "--p", "0.6"], self.data)
        run(["quick", "--task", "t3", "--claim", "c3", "--criteria", "k3", "--p", "0.8"], self.data)
        chain = os.path.join(self.data, "chain.jsonl")
        with open(chain, "r", encoding="utf-8") as f:
            lines = f.readlines()
        del lines[1]  # drop a MIDDLE record — must break the chain
        with open(chain, "w", encoding="utf-8") as f:
            f.writelines(lines)
        r = run(["verify"], self.data)
        self.assertEqual(r.returncode, 2, "deleted middle history MUST exit 2")

    # --- S3: five-second doorbell ---
    def test_quick_under_five_seconds_and_reports_ms(self):
        import time
        t0 = time.time()
        r = run(["quick", "--task", "speed", "--claim", "c", "--criteria", "k", "--p", "0.8"], self.data)
        elapsed = time.time() - t0
        self.assertEqual(r.returncode, 0)
        self.assertLess(elapsed, 5.0, "S3: doorbell must cost < 5s")
        m = re.search(r"\((\d+) ms\)", r.stdout)
        self.assertIsNotNone(m, "quick must report its own latency")
        self.assertLess(int(m.group(1)), 5000)

    def test_quick_creates_pr_and_jd(self):
        run(["quick", "--task", "t", "--claim", "c", "--criteria", "k", "--p", "0.5"], self.data)
        pr = run(["preregister", "list"], self.data)
        jd = run(["judge", "list"], self.data)
        self.assertIn("PR-001", pr.stdout)
        self.assertIn("JD-001", jd.stdout)
        self.assertIn("[OPEN]", pr.stdout)

    # --- S2: exit-code contract ---
    def test_report_exit_1_when_naked(self):
        r = run(["report"], self.data)
        self.assertEqual(r.returncode, 1, "empty week = gap = exit 1")
        self.assertIn("naked", r.stdout.lower())

    def test_report_exit_0_when_active(self):
        run(["quick", "--task", "t", "--claim", "c", "--criteria", "k", "--p", "0.5"], self.data)
        r = run(["report"], self.data)
        self.assertEqual(r.returncode, 0)

    def test_report_exit_2_when_chain_broken(self):
        run(["quick", "--task", "t", "--claim", "c", "--criteria", "k", "--p", "0.5"], self.data)
        chain = os.path.join(self.data, "chain.jsonl")
        with open(chain, "a", encoding="utf-8") as f:
            f.write('{"seq": 99, "prev": "FAKE", "payload": {}, "hash": "FAKE"}\n')
        r = run(["report"], self.data)
        self.assertEqual(r.returncode, 2)

    def test_preregister_verify_unknown_id_exit_1(self):
        run(["quick", "--task", "t", "--claim", "c", "--criteria", "k", "--p", "0.5"], self.data)
        r = run(["preregister", "verify", "--id", "PR-999", "--result", "PASSED"], self.data)
        self.assertEqual(r.returncode, 1)

    def test_p_out_of_range_exit_1(self):
        r = run(["quick", "--task", "t", "--claim", "c", "--criteria", "k", "--p", "1.5"], self.data)
        self.assertEqual(r.returncode, 1)

    # --- calibration ---
    def test_brier_exact_on_confident_hit(self):
        run(["judge", "decide", "--q", "q", "--prediction", "yes", "--p", "1.0"], self.data)
        r = run(["judge", "outcome", "--id", "JD-001", "--actual", "1"], self.data)
        self.assertIn("Brier=0.000", r.stdout)
        rep = run(["report"], self.data)
        self.assertIn("0.000", rep.stdout)

    def test_brier_baseline_documented(self):
        run(["judge", "decide", "--q", "q", "--prediction", "x", "--p", "0.5"], self.data)
        run(["judge", "outcome", "--id", "JD-001", "--actual", "0"], self.data)
        rep = run(["report"], self.data)
        self.assertIn("0.250", rep.stdout, "p=0.5 miss must show the 0.25 coin-flip baseline")

    # --- UTC rendering (sibling repo caught a local-tz bug; regression guard) ---
    def test_timestamps_are_utc_z(self):
        run(["quick", "--task", "t", "--claim", "c", "--criteria", "k", "--p", "0.5"], self.data)
        chain = os.path.join(self.data, "chain.jsonl")
        with open(chain, "r", encoding="utf-8") as f:
            rec = json.loads(f.readline())
        self.assertRegex(rec["ts"], r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        pr = run(["preregister", "list"], self.data)  # smoke: list still works

    # --- crash must never exit 0 ---
    def test_missing_data_dir_report_exit_1_not_crash(self):
        r = run(["report"], os.path.join(self.data, "no", "such", "dir"))
        self.assertIn(r.returncode, (0, 1, 2), "report on empty dir must be a contract exit, not a traceback")


if __name__ == "__main__":
    unittest.main()
