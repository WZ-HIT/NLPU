import unittest
import random
from itertools import combinations

from experiment.trace_cochange import METRICS, feature_sets, stratum, aggregate_results, method_depths, pair_analysis, summarize_cells
from collections import Counter, defaultdict


def method(coverage, depths=None, status="complete"):
    return {"coverage": set(coverage), "depths": depths or {}, "coverage_status": status}


class TraceCochangeTests(unittest.TestCase):
    def test_no_spliced_cross_instance_paths(self):
        document = {"source_test_id": "test", "production_covered_functions": ["a", "b"],
                    "instances": [{"execution_id": x, "evidence_status": "valid"} for x in ("x", "y")],
                    "edges": [{"caller": "test", "callee": "a", "supporting_instances": ["x"]},
                              {"caller": "a", "callee": "b", "supporting_instances": ["y"]}]}
        self.assertEqual(method_depths(document), {"a": 1})
        document["edges"][1]["supporting_instances"].append("x")
        self.assertEqual(method_depths(document), {"a": 1, "b": 2})

    def test_bad_edge_provenance_is_rejected(self):
        document = {"source_test_id": "test", "production_covered_functions": ["a"],
                    "instances": [{"execution_id": "x", "evidence_status": "valid"}],
                    "edges": [{"caller": "test", "callee": "a", "supporting_instances": ["failed"]}]}
        with self.assertRaises(ValueError):
            method_depths(document)

    def test_pair_and_updated_seed_denominators(self):
        methods = {"t.py::A.test_a": method(["x"], {"x": 1}),
                   "t.py::A.test_b": method(["x", "y"], {"x": 2, "y": 1}),
                   "t.py::B.test_c": method(["x"], {"x": 1}),
                   "u.py::test_d": method(["z"], {"z": 1})}
        result = pair_analysis(methods, list(methods)[:2], permutations=20)
        tables = result["tables"]
        self.assertEqual(tables["all_pairs"]["pairs"], 6)
        self.assertEqual(tables["all_coverage:shared"]["both_updated"], 1)
        self.assertEqual(tables["all_coverage:shared"]["one_updated"], 2)
        self.assertEqual(tables["all_coverage:shared"]["p_both_observed_updated"], 1 / 3)
        self.assertEqual(tables["all_coverage:shared"]["p_partner_updated_given_updated_seed"], 1 / 2)
        self.assertEqual(tables["all_coverage:not_shared"]["p_partner_updated_given_updated_seed"], 0)
        self.assertEqual(tables["depth_le_1:shared"]["both_updated"], 0)
        self.assertEqual(tables["depth_le_2:shared"]["both_updated"], 1)
        self.assertEqual(result["updated_pairs"][0]["jaccard"], 0.5)
        self.assertEqual(result["random_partner_update_rate"], 1 / 3)
        for metric in ("all_coverage", "depth_le_1", "rare_5pct"):
            self.assertEqual(tables[metric + ":shared"]["pairs"] + tables[metric + ":not_shared"]["pairs"], 6)

    def test_permutation_owner_matching_controls_class_location(self):
        methods = {"t.py::A.test_a": method(["x"]), "t.py::A.test_b": method(["x"]),
                   "u.py::B.test_c": method(["y"]), "u.py::B.test_d": method(["y"])}
        result = pair_analysis(methods, list(methods)[:2], permutations=100)
        control = result["permutation"]["results"]["source_owner_matched"]["all_coverage"]
        self.assertEqual(control["null_mean_shared_pairs"], 1)
        self.assertEqual(control["upper_tail_fraction_plus_one"], 1)
        self.assertEqual(result, pair_analysis(methods, list(methods)[:2], permutations=100))

    def test_unreachable_is_separate_from_deep(self):
        methods = {"t.py::test_a": method(["x", "y"], {"x": 5}),
                   "t.py::test_b": method(["x", "y"], {"x": 6})}
        result = pair_analysis(methods, list(methods), permutations=0)
        pair = result["updated_pairs"][0]
        self.assertEqual(pair["feature_shared_counts"]["root_unreachable"], 1)
        self.assertEqual(pair["feature_shared_counts"]["depth_ge_4"], 1)
        self.assertEqual(pair["feature_shared_counts"]["depth_le_5"], 0)

    def test_empty_coverage_is_observed_but_empty_union_jaccard_is_undefined(self):
        methods = {"t.py::test_a": method([]), "t.py::test_b": method([])}
        result = pair_analysis(methods, list(methods), permutations=0)
        self.assertIsNone(result["updated_pairs"][0]["jaccard"])
        self.assertEqual(result["tables"]["all_coverage:not_shared"]["both_updated"], 1)

    def test_no_updated_pair_is_not_negative_evidence(self):
        result = pair_analysis({"t.py::test_a": method(["x"])}, ["t.py::test_a"], permutations=0)
        self.assertEqual(result["updated_pairs"], [])
        self.assertIsNone(result["tables"]["all_pairs"]["p_both_observed_updated"])
        self.assertIsNone(summarize_cells({})["p_partner_updated_given_updated_seed"])

    def test_rarity_cutoff_is_label_independent(self):
        methods = {f"t.py::test_{i}": method([f"own_{i}", "common"]) for i in range(20)}
        a = pair_analysis(methods, list(methods)[:2], permutations=0)
        b = pair_analysis(methods, list(methods)[-2:], permutations=0)
        self.assertEqual(a["rare_function_count"], 20)
        self.assertEqual(a["tables"]["rare_5pct:shared"]["pairs"], 0)
        self.assertEqual({r['function']: r['rare_5pct'] for r in a['function_statistics']},
                         {r['function']: r['rare_5pct'] for r in b['function_statistics']})

    def test_macro_does_not_fill_unestimable_pr_with_zero(self):
        a = pair_analysis({"t.py::test_a": method(["x"]), "t.py::test_b": method(["x"])},
                          ["t.py::test_a", "t.py::test_b"], permutations=0)
        b = pair_analysis({"t.py::test_a": method(["x"]), "t.py::test_b": method(["x"])},
                          ["t.py::test_a"], permutations=0)
        for index, result in enumerate((a, b)):
            result.update(cohort="complete_only", base_sha=str(index), pr_id=index)
        aggregate = aggregate_results([a, b])["complete_only"]
        self.assertEqual(aggregate["prs"], 2)
        metric = aggregate["metrics"]["all_coverage"]
        self.assertEqual(metric["macro_fraction_updated_pairs_sharing"], 1)
        self.assertEqual(metric["macro_fraction_denominator_prs"], 1)
        self.assertEqual(metric["macro_partner_update_rate_given_shared_updated_seed"], 0.5)

    def test_stream_all_pair_counts_while_bounding_detailed_report(self):
        methods = {f't.py::test_{i}': method(['x']) for i in range(3)}
        saved = []
        result = pair_analysis(methods, list(methods), permutations=0, pair_sink=saved.append, detail_limit=1)
        self.assertEqual(result['updated_pair_count'], 3)
        self.assertEqual(len(result['updated_pairs']), 1)
        self.assertEqual(len(saved), 3)
        self.assertEqual(result['tables']['all_coverage:shared']['both_updated'], 3)

    def test_fast_permutation_matches_independent_pair_enumeration(self):
        methods = {f't.py::test_{i}': method([str(i % 3), str(i % 2)]) for i in range(7)}
        result = pair_analysis(methods, list(methods)[:4], permutations=100, seed=17)
        rng = random.Random(17)
        ids = sorted(methods)
        total = 0
        for _ in range(100):
            chosen = rng.sample(range(7), 4)
            total += sum(bool(methods[ids[a]]['coverage'] & methods[ids[b]]['coverage']) for a, b in combinations(chosen, 2))
        self.assertEqual(result['permutation']['results']['uniform']['all_coverage']['null_mean_shared_pairs'], total / 100)

    def test_all_feature_and_location_cells_match_exhaustive_pairs(self):
        rng = random.Random(83)
        for n in [0, 1, 2, 7, 23]:
            methods = {}
            for i in range(n):
                coverage = {str(j) for j in range(9) if rng.random() < .3}
                methods[f'f{i%2}.py::C{i%3}.test_{i}'] = method(coverage, {s: rng.randint(1, 7) for s in coverage if rng.random() < .8})
            gold = set(sorted(methods)[::3])
            result = pair_analysis(methods, gold, permutations=0)
            frequency = Counter(s for m in methods.values() for s in m['coverage'])
            rare = {s for s, c in frequency.items() if c / n <= .05}
            features = {t: feature_sets(m, rare) for t, m in methods.items()}
            expected = defaultdict(lambda: defaultdict(Counter))
            for a, b in combinations(sorted(methods), 2):
                group = 'both_updated' if a in gold and b in gold else 'one_updated' if a in gold or b in gold else 'neither_updated'
                for loc in ['all', stratum(a, b)]:
                    expected[loc]['all_pairs'][group] += 1
                    for key in METRICS:
                        condition = 'shared' if features[a][key] & features[b][key] else 'not_shared'
                        expected[loc][key+':'+condition][group] += 1
            for loc, tables in expected.items():
                actual = result['tables'] if loc == 'all' else result['location_strata'][loc]
                for key in ['all_pairs', *[m+':'+s for m in METRICS for s in ['shared','not_shared']]]:
                    self.assertEqual(actual[key], summarize_cells(tables[key]), (n, loc, key))


if __name__ == "__main__":
    unittest.main()
