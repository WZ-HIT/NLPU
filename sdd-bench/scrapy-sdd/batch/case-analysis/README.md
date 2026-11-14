# 代表性 PR 连接关系案例分析

本目录用于追踪 Scrapy 历史 PR 中**被修改的既有测试**与**包内 Python 生产改动**之间的连接关系。它不是模型输入，也不是最终实验指标；当前定位是**开发/校准集**，用于定义关联类型、发现失败模式、调整后续方法。

## 当前状态

- 已完成 57 个候选 PR 的规则预分：`preclassification.json`（主导类型分布：no_edge 38、direct 9、tie 6、indirect 4）。
- 已生成 5 个试点 case：`cases/pr*.json` 与 `cases/pr*.md`，均为 `draft`，边与反事实全部是候选。
- 试点合计 12 条候选边（direct 4、indirect 8）、22 个无连接生产符号。
- 等待人工全量复核；复核完成前不选剩余 PR、不冻结 schema。
- 尚未运行任何模型、Docker 或新实验。

## 冻结口径

| 项目 | 口径 |
| --- | --- |
| 样本来源 | 现有 98 个 `MIXED_CODE_AND_TEST_PR` benchmark PR |
| 测试范围 | 只纳入 base 已存在、PR 中被修改的既有测试 |
| 生产代码 | 只算包内 Python 源文件，即 `scrapy/**.py` |
| 分析单位 | PR 为容器，内部记录方法级边 `(测试, 生产符号)` |
| 直接关联 | 最短路径 1 跳 |
| 多层间接 | 最短路径 ≥2 跳；多跳调用/import、数据或行为传播、配置/注册/事件都算，用 `evidence` 区分 |
| 跳数 | 记录真实最短路径，不设上限；非调用关系 `hops=null` |
| 无测试连接 | 找不到直接/间接关系，且人工确认无语义影响；按方法级边判断 |
| 第三类判定 | 反事实三分类：`no_update_needed` / `missed` / `unknown`；需要新增测试的情况另记 `coverage_gap` |
| 改动性质 | 所有生产改动都纳入，用 `change_kind` 标注 `behavior/refactor/typing/docs/unknown` |
| 漏更新标准 | 既有测试的断言或执行路径受行为变化影响、本应修改，才算 `missed` |
| 版本边界 | base = PR base revision，是方法唯一可见版本；head/merge 只用于建边、分析和评分 |
| 评分 | 双层：测试级正例 = 实际被修改的既有测试；边级 = 人工确认的直接/间接边。漏更新、coverage gap、无法判定单列 |
| 复核 | 主判 + 隔期第二遍；改判保留原判断与理由 |
| 产出 | 结构化 case JSON + 案例说明 Markdown；边表可从 case 派生 |
| 存放 | 本目录纳入程序 Git；不复制完整 gold，不进入 `context/` |

## 候选池与排除

`preclassify.py` 从 98 个 benchmark PR 中筛出 57 个候选：

- 排除 15 个：分类为 mixed，但过滤后没有 `scrapy/**.py` 生产改动（实际只改了 `pyproject.toml`、`tox.ini` 等）。
- 排除 9 个：修改的既有测试超过 20 个（29–175 个），属大规模重构；按冻结口径不进入案例，避免边表失控。
- 剩余 57 个：修改测试 1–20 个，且至少有一个包内 Python 生产改动。

预分结果是**候选**，不是 ground truth。弱证据（`module_import`、`name_overlap`、`diff_proximity`）只作提示，不直接算作间接关联；只有当 base 调用图能给出真实路径、且该生产符号确实在 PR 改动里时，弱证据才会升级为 `direct`/`indirect`（`source=base_ast_weak_upgrade`，置信度 `low`）。

调用图节点是**函数叶子名**，与 `experiment/pair_tests.py` 一致。这会把不同模块的同名函数合并，因此每条间接边都会在 `rationale` 里列出有歧义的中间节点（如 `process_request` 在全仓有 15 个定义），复核时必须确认模块级路径。

## 试点 PR

| PR | 选样层 | 预分计数（direct/indirect/weak/no_edge） | 选样理由 |
| --- | --- | --- | --- |
| [scrapy/scrapy#7605](https://github.com/scrapy/scrapy/pull/7605) | direct | 1/0/0/0 | 1 个既有测试 → 1 个生产函数，链路清晰，用于验证直接边与 hunk 映射 |
| [scrapy/scrapy#7647](https://github.com/scrapy/scrapy/pull/7647) | indirect | 0/1/0/0 | 1 个既有测试，证据为 `static_call_path`，用于验证多层间接与跳数记录 |
| [scrapy/scrapy#7520](https://github.com/scrapy/scrapy/pull/7520) | no_edge | 0/0/0/3 | 1 个既有测试、3 个生产符号，无直接/间接候选，用于验证无测试连接与反事实判断 |
| [scrapy/scrapy#6546](https://github.com/scrapy/scrapy/pull/6546) | mixed | 3/0/1/15 | 4 个测试，同时有直接边与大量无连接生产符号，用于验证类型共存与主导类型判定 |
| [scrapy/scrapy#7684](https://github.com/scrapy/scrapy/pull/7684) | mixed | 0/7/2/4 | 9 个测试，含间接边、弱证据与无连接符号，用于验证弱证据处理与混合边表 |

试点目标是把 schema、证据字段、反事实判定和复核流程跑通；试点完成后冻结 schema，再选剩余 7–10 个 PR。

## 文件与用法

```text
batch/case-analysis/
├── README.md
├── preclassification.json          # 57 个候选的规则预分（只读候选）
├── edges.jsonl                     # 由 5 个试点 case 派生的扁平边表
├── cases/
│   ├── pr7605.json                 # 单案例结构化记录
│   └── pr7605.md                   # 单案例可读说明
├── schema/case-record.schema.json  # case JSON Schema
└── tools/
    ├── preclassify.py              # 预分脚本
    ├── callgraph.py                # 叶子名调用图（两个脚本共用）
    └── build_pilot_cases.py        # 试点 case 生成脚本
```

重新生成预分与试点 case：

```bash
python3 sdd-bench/scrapy-sdd/batch/case-analysis/tools/preclassify.py
python3 sdd-bench/scrapy-sdd/batch/case-analysis/tools/build_pilot_cases.py
```

两个脚本只读本地 inventory、gold store、raw PR 记录和 base worktree，不调用模型或 Docker。调用图按需构建：只有出现弱证据或需要间接路径的 PR 才解析全仓 AST，全量预分约 30 秒。

## 数据边界

- `batch/gold/` 与 `batch/runs/round-*/` 是 gitignore 的本地数据；本目录只引用路径、符号、hunk 范围和哈希，案例说明只内联少量必要片段。
- 完整 `gold_test`、`test_patches`、`production_patches` 不复制到本目录或 `context/`。
- 方法评估时只允许使用 base revision；head/merge 的 diff 只供建边、分析与评分。
- 判边阶段不看现有 SDD 预测；边表冻结后才附 cc-sdd / openspec / speckit 的结果。

## 复核与验收

- 每条边有证据类型、跳数、理由、置信度和 `status`（`candidate/confirmed/rejected`）。
- 每个无连接生产符号有 `counterfactual`、`change_kind`、置信度与理由。
- 三类的 PR 覆盖各 ≥4 个，试点完成后补足。
- 隔期复核改判率 ≤20%，或所有改判都记录在 `review.changed_verdicts`。

试点复核需要给出的结论：

1. 12 条候选边逐条确认或推翻，并说明模块级路径（尤其 `process_request`、`_test_request`、`get_crawler` 这类同名叶子）。
2. 22 个无连接生产符号逐个判定 `no_update_needed` / `missed` / `unknown`，并标 `change_kind`；若 `missed`，在 `affected_existing_tests` 里写出应改而未改的既有测试。
3. 指出预分漏掉的非调用关系：fixture、配置项、事件/信号、数据传播。
4. 判断是否需要 `coverage_gap`（应当新增测试而不是修改既有测试）。
5. 复核完成后冻结 schema 字段与判据，再按主导类型配额选剩余 7–10 个 PR。
