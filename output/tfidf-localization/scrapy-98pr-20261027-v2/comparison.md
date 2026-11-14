# TF-IDF + 余弦相似度与 BM25 对比

同一批 98 个 PR，其中 96 个可评分。
已校验输入哈希、查询、base、候选源码文档、分词、评价标签及评分 PR 范围一致。

TF-IDF 使用原始 TF、平滑 IDF 与 L2 归一化，仅在各 base 测试集合拟合。
公式依据：[TfidfTransformer](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfTransformer.html)。

| k | 指标 | BM25 | TF-IDF + 余弦 | 差值（百分点） |
|---:|---|---:|---:|---:|
| 50 | Macro Recall@k | 41.49% | 41.37% | -0.12 |
| 50 | Hit@k 任务命中率 | 62.50% | 59.38% | -3.12 |
| 50 | Macro Precision@k 候选命中率 | 4.42% | 4.50% | +0.08 |
| 50 | Micro Recall@k | 18.52% | 18.86% | +0.35 |
| 100 | Macro Recall@k | 53.28% | 48.60% | -4.68 |
| 100 | Hit@k 任务命中率 | 75.00% | 66.67% | -8.33 |
| 100 | Macro Precision@k 候选命中率 | 3.15% | 3.10% | -0.04 |
| 100 | Micro Recall@k | 26.38% | 26.03% | -0.35 |
| 200 | Macro Recall@k | 61.93% | 57.89% | -4.04 |
| 200 | Hit@k 任务命中率 | 83.33% | 77.08% | -6.25 |
| 200 | Macro Precision@k 候选命中率 | 2.04% | 2.03% | -0.02 |
| 200 | Micro Recall@k | 34.24% | 33.97% | -0.26 |

## 命中目标数量与逐 PR 差异

| k | BM25 命中目标 | TF-IDF 命中目标 | TF-IDF 较好 PR | 较差 PR | 持平 PR |
|---:|---:|---:|---:|---:|---:|
| 50 | 212 | 216 | 12 | 14 | 70 |
| 100 | 302 | 298 | 12 | 19 | 65 |
| 200 | 392 | 389 | 11 | 14 | 71 |

较好/较差按同一 PR 的 Recall@k 比较。结果仅解释当前固定样本与配置，未进行统计显著性检验。
完整结果见 [report.md](report.md)，逐 PR 对照见 [comparison-per-pr.csv](comparison-per-pr.csv)，
候选清单见 [candidates-top200.csv](candidates-top200.csv)，独立重算见 [verification.json](verification.json)。
