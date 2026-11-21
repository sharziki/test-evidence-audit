import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from audit import audit, load_pairs, seconds_to_ns

EXAMPLES = Path(__file__).parent / "examples"


def audit_example(name):
    pairs = load_pairs(EXAMPLES / f"{name}.csv", "Dev5_BCLS_ai_time", "BENCH-TEMP", "REF-TEMP")
    return audit(pairs, 0, seconds_to_ns("30"), seconds_to_ns("2"), Decimal("0.5"))


class CalibrationTests(unittest.TestCase):
    def test_complete_agreement_passes(self):
        self.assertEqual(audit_example("clean")["verdict"], "pass")

    def test_observed_disagreement_fails(self):
        report = audit_example("complete")
        self.assertEqual(report["verdict"], "fail")
        self.assertEqual(len(report["out_of_tolerance_samples"]), 7)

    def test_missing_violation_prevents_false_pass(self):
        report = audit_example("logger_dropout")
        self.assertEqual(report["samples_only_verdict"], "pass")
        self.assertEqual(report["verdict"], "insufficient_evidence")
        self.assertEqual(report["gaps"], [{"from_s": 11, "to_s": 19, "duration_s": 8}])

    def test_missing_window_boundary_is_counted(self):
        samples = [(seconds_to_ns(second), Decimal("0")) for second in ("3", "4", "5")]
        report = audit(samples, 0, seconds_to_ns("5"), seconds_to_ns("2"), Decimal("0.5"))
        self.assertEqual(report["verdict"], "insufficient_evidence")
        self.assertEqual(report["gaps"], [{"from_s": 0, "to_s": 3, "duration_s": 3}])

    def test_uncertainty_keeps_borderline_agreement_unresolved(self):
        samples = [(0, Decimal("0.45")), (seconds_to_ns("1"), Decimal("-0.45"))]
        report = audit(samples, 0, seconds_to_ns("1"), seconds_to_ns("1"),
                       Decimal("0.50"), Decimal("0.10"))
        self.assertEqual(report["samples_only_verdict"], "pass")
        self.assertEqual(report["verdict"], "insufficient_evidence")
        self.assertEqual(len(report["uncertainty_overlap_samples"]), 2)
        self.assertEqual(Decimal(report["mean_signed_difference"]), 0)

    def test_large_disagreement_still_fails_with_uncertainty(self):
        samples = [(0, Decimal("-0.7")), (seconds_to_ns("1"), Decimal("0"))]
        report = audit(samples, 0, seconds_to_ns("1"), seconds_to_ns("1"),
                       Decimal("0.5"), Decimal("0.1"))
        self.assertEqual(report["verdict"], "fail")
        self.assertEqual(report["out_of_tolerance_samples"][0]["error_bounds"], ["0.6", "0.8"])

    def test_numeric_millisecond_clock_preserves_relative_subsecond_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.csv"
            path.write_text("time,sensor,reference\n1763788180000.000001,20,20\n1763788180000.000002,21,20\n")
            self.assertEqual(load_pairs(path, "time", "sensor", "reference", "ms"), [(0, 0), (1, 1)])

    def test_guided_profile_replays_and_saves_report(self):
        command = [sys.executable, str(EXAMPLES.parent / "audit.py")]
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            report = Path(directory) / "report.json"
            setup = subprocess.run(
                [*command, str(EXAMPLES / "clean.csv"), "--setup", str(profile)],
                input="\n\n2\n3\n\n30\n0.5\n2\n\n",
                text=True, capture_output=True,
            )
            self.assertEqual(setup.returncode, 0, setup.stderr)
            self.assertEqual(json.loads(profile.read_text())["sensor"], "BENCH-TEMP")
            replay = subprocess.run(
                [*command, str(EXAMPLES / "logger_dropout.csv"), "--profile", str(profile),
                 "--report", str(report)],
                text=True, capture_output=True,
            )
            self.assertEqual(replay.returncode, 3, replay.stderr)
            self.assertIn("longest 11 to 19 s", replay.stdout)
            self.assertEqual(json.loads(report.read_text())["verdict"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
