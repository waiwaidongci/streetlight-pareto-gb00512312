import time
import unittest
from unittest import mock

from src.domain import circuit
from src.domain.circuit import Search, build_model, run_diagnosis, validate_rows, verify
from src.domain.circuit_demo import circuit_rows, supplement_rows

PARAMS = {"max_breaks": 12, "pass_seconds": 50}


def solve(rows, params=None, checkpoint=None, budget=50):
    return run_diagnosis(rows, params or PARAMS, checkpoint, budget)


class ValidateTest(unittest.TestCase):
    def test_demo_rows_are_valid(self):
        records = validate_rows(circuit_rows())
        self.assertEqual(len(records), 1 + 8 + 1 + 6 + 5)

    def test_duplicate_segment_rejected(self):
        rows = circuit_rows()
        rows.append(dict(rows[1]))
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_rows(rows)

    def test_switch_must_reference_segment(self):
        rows = circuit_rows()
        rows.append({"record_type": "开关", "switch_id": "SW-99", "segment_id": "SEG-99",
                     "switch_state": "闭合"})
        with self.assertRaisesRegex(ValueError, "不存在的线路"):
            validate_rows(rows)

    def test_observation_must_reference_lamp(self):
        rows = circuit_rows()
        rows.append({"record_type": "观测", "site_id": "LH-99", "observed": "亮"})
        with self.assertRaisesRegex(ValueError, "不在灯组记录中"):
            validate_rows(rows)

    def test_second_observation_same_window_rejected(self):
        rows = circuit_rows()
        rows.append({"record_type": "观测", "site_id": "LH-01", "observed": "灭"})
        with self.assertRaisesRegex(ValueError, "同一时段"):
            validate_rows(rows)


class SolveTest(unittest.TestCase):
    def test_demo_batch_optimum(self):
        done, _, result = solve(circuit_rows())
        self.assertTrue(done)
        self.assertEqual(result["verdict"], "explained")
        self.assertEqual(result["breakpoint_count"], 3)
        self.assertEqual(result["solution_count"], 2)
        self.assertEqual([item["segment_id"] for item in result["core"]], ["SEG-03", "SEG-04"])
        self.assertEqual([item["segment_id"] for item in result["optional"]], ["SEG-06", "SEG-07"])
        self.assertEqual(result["solutions"][0]["breakpoints"], ["SEG-03", "SEG-04", "SEG-06"])
        self.assertEqual(result["solutions"][1]["breakpoints"], ["SEG-03", "SEG-04", "SEG-07"])

    def test_trace_is_recomputable(self):
        done, _, result = solve(circuit_rows())
        lamps = {row["site_id"]: row for row in result["trace"]["lamps"]}
        self.assertEqual(lamps["LH-01"]["simulated"], "亮")
        self.assertIn("SEG-01", lamps["LH-01"]["witness"])
        self.assertEqual(lamps["LH-03"]["simulated"], "灭")
        self.assertIn("SEG-03、SEG-04", lamps["LH-03"]["witness"])
        self.assertEqual(lamps["LH-05"]["witness"], "断点 SEG-06 切断全部来路")
        self.assertEqual(lamps["LH-06"]["witness"], "接线与开关记录下本就无来电路径")
        self.assertEqual(lamps["LH-04"]["match"], "—")
        for row in result["trace"]["lamps"]:
            if row["observed"] != "未观测":
                self.assertEqual(row["match"], "符合")

    def test_supplement_batch_is_unsat_and_suggests_discards(self):
        done, _, result = solve(supplement_rows())
        self.assertTrue(done)
        self.assertEqual(result["verdict"], "unsat")
        unsat = result["unsat"]
        self.assertEqual(unsat["discard_count"], 1)
        dropped = {tuple(drop["site_id"] for drop in item["drop"]) for item in unsat["sets"]}
        self.assertEqual(dropped, {("LH-03",), ("LH-04",)})
        self.assertEqual(unsat["proof"]["breakpoint_count"], 1)
        self.assertEqual(unsat["proof"]["breakpoints"], ["SEG-06"])

    def test_verify_recomputes_any_scheme(self):
        rows = circuit_rows()
        outcome = verify(rows, ["SEG-03", "SEG-04", "SEG-07"])
        self.assertTrue(outcome["explained"])
        self.assertEqual(outcome["breakpoint_count"], 3)
        bad = verify(rows, ["SEG-03", "SEG-04"])
        self.assertFalse(bad["explained"])
        self.assertEqual(bad["mismatches"], ["LH-05"])
        with self.assertRaisesRegex(ValueError, "不在记录中"):
            verify(rows, ["SEG-99"])

    def test_resume_matches_single_pass(self):
        rows = circuit_rows()
        model = build_model(validate_rows(rows))
        fresh = Search(model, 12)
        self.assertTrue(fresh.step(time.monotonic() + 30))
        # 用已过期的时限逼出中间进度，再凭进度续算到完成。
        paused = Search(model, 12)
        self.assertFalse(paused.step(time.monotonic() - 1))
        state = paused.state()
        resumed = Search(model, 12, state)
        self.assertTrue(resumed.step(time.monotonic() + 30))
        self.assertEqual(resumed.total, fresh.total)
        self.assertEqual(resumed.display, fresh.display)
        self.assertEqual(resumed.core, fresh.core)
        self.assertEqual(resumed.union, fresh.union)
        self.assertGreaterEqual(resumed.visited + resumed.excluded, 0)

    def test_run_diagnosis_requeues_with_checkpoint(self):
        clock = {"now": 0.0}
        def fake_monotonic():
            clock["now"] += 0.6
            return clock["now"]
        with mock.patch.object(circuit.time, "monotonic", fake_monotonic):
            done, checkpoint, _ = run_diagnosis(circuit_rows(), PARAMS, None, 1)
        self.assertFalse(done)
        self.assertEqual(checkpoint["phase"], "search")
        done, checkpoint, result = run_diagnosis(circuit_rows(), PARAMS, checkpoint, 50)
        self.assertTrue(done)
        self.assertEqual(result["verdict"], "explained")
        self.assertEqual(result["breakpoint_count"], 3)

    def test_discard_phase_also_resumes(self):
        clock = {"now": 100.0}
        def fake_monotonic():
            clock["now"] += 0.6
            return clock["now"]
        with mock.patch.object(circuit.time, "monotonic", fake_monotonic):
            done, checkpoint, _ = run_diagnosis(supplement_rows(), PARAMS, {"phase": "discard"}, 1)
        self.assertFalse(done)
        self.assertEqual(checkpoint["phase"], "discard")
        done, _, result = run_diagnosis(supplement_rows(), PARAMS, checkpoint, 50)
        self.assertTrue(done)
        self.assertEqual(result["verdict"], "unsat")
        self.assertEqual(result["unsat"]["discard_count"], 1)

    def test_lit_lamp_beyond_open_switch_is_unsat(self):
        rows = circuit_rows()
        rows.append({"record_type": "观测", "site_id": "LH-06", "observed": "亮"})
        rows = [row for row in rows
                if not (row["record_type"] == "观测" and row["site_id"] == "LH-06" and row["observed"] == "灭")]
        done, _, result = solve(rows)
        self.assertTrue(done)
        self.assertEqual(result["verdict"], "unsat")
        self.assertEqual(result["unsat"]["discard_count"], 1)

    def test_no_dark_observations_needs_no_breaks(self):
        rows = [row for row in circuit_rows()
                if not (row["record_type"] == "观测" and row["observed"] == "灭")]
        done, _, result = solve(rows)
        self.assertTrue(done)
        self.assertEqual(result["verdict"], "explained")
        self.assertEqual(result["breakpoint_count"], 0)

    def test_over_limit_when_cap_too_small(self):
        done, _, result = solve(circuit_rows(), {"max_breaks": 2, "pass_seconds": 50})
        self.assertTrue(done)
        self.assertEqual(result["verdict"], "over_limit")


if __name__ == "__main__":
    unittest.main()
