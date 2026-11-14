import unittest

from experiment.trace_recall_gaps import sharing, summarize


def record(coverage=(), depths=None, status="complete"):
    return {"coverage": set(coverage), "depths": depths or {}, "coverage_status": status}


class TraceRecallGapTests(unittest.TestCase):
    def test_counts_missed_once_and_requires_same_function_shallow_on_both_sides(self):
        records = {"s1": record(["x", "y"], {"x": 1, "y": 3}),
                   "s2": record(["x"], {"x": 1}),
                   "miss": record(["x", "y"], {"x": 3, "y": 1})}
        result = sharing({"miss"}, {"s1", "s2"}, records, {"complete"})
        evidence = result["missed"][0]["metrics"]
        self.assertTrue(evidence["depth_le_3"]["shared"])
        self.assertEqual(len(evidence["all_coverage"]["witnesses"]), 2)
        self.assertFalse(evidence["depth_le_2"]["shared"])
        self.assertEqual(evidence["depth_le_2"]["state"], "not_shared")

    def test_unreachable_coverage_is_not_shallow_and_unknown_is_not_empty(self):
        records = {"s": record(["x"], {}), "m": record(["x"], {}),
                   "u": record(status="unavailable")}
        result = sharing({"m", "u"}, {"s"}, records, {"complete"})
        m, u = result["missed"]
        self.assertTrue(m["metrics"]["all_coverage"]["shared"])
        self.assertFalse(m["metrics"]["depth_le_3"]["shared"])
        self.assertEqual(u["metrics"]["all_coverage"]["state"], "unknown")
        self.assertEqual(result["eligible_missed"], 1)

    def test_incomplete_seed_prevents_claiming_nonsharing(self):
        records = {"s": record(["x"], {"x": 1}),
                   "p": record(["y"], {"y": 1}, "partial"),
                   "m": record(["y"], {"y": 1})}
        primary = sharing({"m"}, {"s", "p"}, records, {"complete"})
        exploratory = sharing({"m"}, {"s", "p"}, records, {"complete", "partial"})
        self.assertEqual(primary["missed"][0]["metrics"]["depth_le_1"]["state"], "unknown")
        self.assertTrue(exploratory["missed"][0]["metrics"]["depth_le_1"]["shared"])

    def test_partial_selection_and_distinct_pr_sdd_denominators(self):
        records = {"s": record(["x"], {"x": 1}), "m": record(["x"], {"x": 2}),
                   "u": record(status="not_discovered")}
        evidence = sharing({"m", "u"}, {"s"}, records, {"complete"})
        rows = [{"pr_id": 1, "recall_state": "partial", "fn": 2, "sharing": evidence},
                {"pr_id": 1, "recall_state": "partial", "fn": 2, "sharing": evidence},
                {"pr_id": 2, "recall_state": "zero", "fn": 20, "sharing": None}]
        result = summarize(rows)
        self.assertEqual(result["partial_tasks"], 2)
        self.assertEqual(result["partial_unique_prs"], 1)
        self.assertEqual(result["missed_total"], 4)
        self.assertEqual(result["metrics"]["all_coverage"]["shared_missed"], 2)
        self.assertEqual(result["metrics"]["all_coverage"]["fraction_all_missed"], .5)
        self.assertEqual(result["metrics"]["all_coverage"]["fraction_eligible_missed"], 1.)


if __name__ == "__main__":
    unittest.main()
