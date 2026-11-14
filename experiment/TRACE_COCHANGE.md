# 覆盖共享、调用层级与测试共同修改

`trace_cochange.py` 是宿主侧回顾性分析程序。输入为已经冻结的 base
动态覆盖包与已有 `testcase-v1` 方法级修改标签。它不执行新测试、不调用
模型、不修改覆盖包，也不生成供 SDD 使用的标签增强材料。

```bash
python3 -m experiment.trace_cochange \
  --trace-bundle /path/to/base-A/test-traces \
  --trace-bundle /path/to/base-B/test-traces \
  --retrieval-run /path/to/sealed-retrieval-run \
  --output /path/to/new-host-only-analysis \
  --permutations 10000
```

`retrieval-run` 使用既有实验目录中的 `per-pr.json`、`evaluation/pr-*-labels.json`
及 `corpora/<base>.json`，不使用检索排名或分数。程序核查覆盖包文件封存、标签内容
封存、base/index 身份及候选源码哈希。一个 base 只能显式选择一个覆盖包，避免
混合不同执行环境。输出目录必须是新目录。

研究单位是同一个 PR/base 中的两个不同源码测试方法。参数化与继承执行实例归并
到实际定义方法，同一方法不与自己组成测试对。主分析仅纳入全部执行实例均有有效
覆盖的 `complete` 方法；`complete + partial` 是单列的探索性分析。未发现和覆盖
不可用方法保持未知，不能用空集合代替。未观察到更新也不能等同于不需要更新。

程序区分两个方向：

- 共同更新测试对中，共享生产函数的比例 `P(shared | both updated)`。
- 共享测试对中，两者均被观察到更新的比例 `P(both updated | shared)`；另报更适合
  从已更新测试向邻居扩展的 `P(partner updated | seed updated, shared)`。

第二个方向同时与不共享覆盖的测试对、随机伙伴、同文件/源码 owner 分层及保留
每个源码 owner 更新数量的随机对照比较。若共享无序对有 `b` 个两者更新、`o` 个
仅一者更新，那么已更新种子的共享伙伴更新率是 `2b / (2b + o)`；不能把它与
`b / 全部共享对` 混用。

层级是每个有效执行实例的函数调用图中，从测试根出发的 BFS 最短距离；再跨
同一方法的实例取最小值。使用边的 `supporting_instances` 避免跨实例拼接路径。
函数图已折叠调用次数，因此 BFS 距离不等于实际执行栈深度，也不证明断言因果依赖。
外部或不透明边界造成的根不可达覆盖单列，不解释为无覆盖或最深层。

完整覆盖、内部根可达、深度≤1/2/3/5、深度≥4、根不可达、低频函数共享分别统计。
低频定义固定为覆盖该函数的测试数不超过当前分析候选数的 5%，不按修改标签调参。
Jaccard 用于完整生产函数集合；两侧均为空时其值为 `null`。

输出包括覆盖缺失的 base/PR 台账、逐 PR/分析 cohort 的完整计数与对照、共同更新
测试对的全部共享函数及两侧层级、函数普遍度、描述性随机对照、等权 PR 宏平均和
合并计数。所有输入文件和分析结果保留哈希。某些 cohort 没有可分析的共同更新
测试对时，相应比例为未知，不补为零。

v1.1 为大范围运行增加逐 PR 的 `*-updated-pairs.csv`，保存所有共同更新对的计数。
JSON 与报告最多列出按身份排序的前 100 对逐函数详情；全量统计和 CSV 不裁剪。
随机对照通过测试邻接位集合精确计算，与逐对枚举的分数一致，避免大规模修改
PR 的抽样开销随更新测试数的平方增长。

v1.2 将全部条件和位置分层的测试对计数也改为精确倒排索引统计。输入、层级定义、
分母和随机种子保持一致。`trace_analysis_parallel.py` 可以按 base 并行运行，合并时
检查全部 PR 身份和输入哈希；旧的逐对实现已完成的结果可作为等价性核对。
`trace_relationship_report.py` 在完成的宿主分析上补充相同 PR 分母对照、按 base 聚类
的 bootstrap 区间与研究解读，不修改任何原始覆盖包。

随机对照只描述当前 PR。不能把数百万相关测试对当作独立样本来宣称显著性；
跨 PR 推广应关注 PR/base 的覆盖范围、修改类型和按 base/时间聚类的不确定性。
当前程序回答每个 PR 内的关联；若研究一对测试跨历史 PR 的共同修改频率，必须
另外定义两者同时存在且可观测的机会窗口。

```bash
python3 -m unittest -v tests.test_trace_cochange
```
