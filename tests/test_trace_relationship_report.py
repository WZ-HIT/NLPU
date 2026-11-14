import unittest

from experiment.trace_relationship_report import cluster_mean


class ClusterBootstrapTests(unittest.TestCase):
    def test_mean_keeps_equal_pr_weight_with_base_clusters(self):
        result = cluster_mean([('a', 1), ('a', 1), ('b', 0)], draws=1000)
        self.assertEqual(result['mean'], 2 / 3)
        self.assertEqual(result['n_prs'], 3)
        self.assertEqual(result['n_bases'], 2)
        self.assertEqual((result['low'], result['high']), (0, 1))

    def test_one_base_cannot_estimate_cluster_uncertainty(self):
        result = cluster_mean([('a', 0), ('a', 1)])
        self.assertEqual(result['mean'], 0.5)
        self.assertIsNone(result['low'])
        self.assertIsNone(result['high'])


if __name__ == '__main__':
    unittest.main()
