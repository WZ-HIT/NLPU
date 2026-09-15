# PR Method-Level Test Update Dataset

本项目从 GitHub 上已合并且 CI 成功的 Python PR 中构建 test-case 级测试更新样本。每条输入包含 PR 前旧 pytest test 和自然语言描述；可靠配对时额外提供 PR 后 focal method。开发者最终合并的更新测试只作为 raw 数据中的隐藏 gold。

默认 `demo_pipeline.py` 会：

1. 采集 merged PR，并保存可复现的 base/head/merge revision 元数据。
2. 对 merged、CI success 且修改 pytest 文件的 PR 提取测试；是否存在生产文件或可靠 focal 不再是提取前提。
3. checkout base/head 完整源码，以 AST 提取 focal method、old test 和隐藏 gold test。
4. 通过可选 coverage、静态调用路径、import、命名和 diff 邻近关系完成配对。
5. 将 test change 和配对补充到 `raw_prs`，并按每个 modified test 构建无 gold 泄漏的 prompt。
6. 为兼容已有流程，继续生成旧文件级 dataset、prompt 和质量报告。

## Files

- `collector/`: 采集 GitHub PR、CI、base/head revision 和自然语言元数据
- `experiment/ast_extract.py`: 从完整 checkout 提取发生变化的函数、方法和 pytest test
- `experiment/pair_tests.py`: test-focal 配对、证据评分和准入判定
- `experiment/mine_samples.py`: 管理 clone/worktree，并将 test change 与方法级配对补充进 raw JSONL
- `build_prompts.py`: 从 raw 数据按 test-case 粒度构建 `focal_guided`/`test_only` prompt
- `demo_pipeline.py`: 串联采集、方法挖掘、method prompt 和兼容输出
- `analyze_intent.py`: PR change-intent classification via the Claude API
- `analyze_nl_thresholds.py`: derive NL quality thresholds from collected data
- `plot_nl_thresholds.py`: visualise NL length distributions
- `output/raw_prs/<owner>__<repo>.jsonl`: 完整研究记录，包含隐藏 gold，不能直接作为模型输入
- `output/prompt/<owner>__<repo>.json`: 方法级 OpenSpec/LLM 输入，不含 gold
- `output/dataset.jsonl`: generated dataset samples
- `output/quality_report.json`: generated quality report

## Run

Set a GitHub token first:

```bash
export GITHUB_TOKEN=your_token_here
```

Then collect real PRs and run the full pipeline:

```bash
python3 demo_pipeline.py --owner psf --repo requests --limit 50
```

默认启用 `--resume`：已有完整记录会跳过；缺少 `base_sha`、`head_sha` 或 `merged_at` 的旧缓存记录会重新请求 GitHub 并原子替换对应 raw JSONL。若要忽略缓存重新采集：

```bash
python3 demo_pipeline.py --owner psf --repo requests --limit 50 --no-resume
```

常用选项：

```bash
# 指定可复用 clone 缓存和可选 coverage 映射
python3 demo_pipeline.py \
  --owner scrapy --repo scrapy --limit 50 \
  --repo-cache-dir /tmp/nlpu-repository-cache \
  --coverage-map coverage-map.json

# 只运行旧文件级流程，不 checkout 仓库或挖掘方法
python3 demo_pipeline.py --owner scrapy --repo scrapy --limit 50 --no-mine-methods

# raw 数据已有 test_change/method pair 时，单独重建两类 prompt
python3 build_prompts.py
```

coverage 文件的顶层 key 为 `<owner>/<repo>#<pr_id>`；值为 `{test_node_id: [focal_node_id, ...]}`。node ID 格式为 `<file>::<qualified_name>`。

## Output Boundary

- `output/raw_prs/*.jsonl` 包含 `gold_test`，只用于构建和验证。
- `output/prompt/*.json` 包含 old test 和自然语言描述；`focal_guided` 额外包含 post-PR focal method，`test_only` 的 focal 字段为 null。
- `output/prompts.jsonl` 是为兼容保留的文件 diff prompt，可能包含真实测试 diff，不应用作防泄漏实验输入。
- `output/raw_prs/manifest.json` 和 `output/prompt/manifest.json` 分别记录 schema、来源与数量。

详细字段与 gold 隔离规则见 `output/DATASET_SCHEMA.md`。

## Current Validation Scope

- 第一阶段仅支持 Python 与 pytest；每条 prompt 对应一个 base/head 中均存在的 modified test。
- accepted 配对必须有 coverage、直接静态调用或短静态调用路径证据，且不能存在最高分并列。
- `gold_on_head=pass` 当前来自目标 PR 的成功 CI rollup，来源记录为 `pr_ci_rollup`，不是本地重跑单个 gold test。
- 如需更强的动态验证，可提供 coverage map，或在后续验证阶段加入隔离环境中的 head/base 测试执行。

## Downstream Tools

- `python3 analyze_nl_thresholds.py [--fetch owner/repo ...]` — derive NL length thresholds
- `python3 analyze_intent.py --input output/dataset.jsonl` — classify PR change intent
- `python3 plot_nl_thresholds.py` — visualise NL length distributions

## How To Extend It

- Replace heuristic verification with Docker-based build and test execution
- Add SQLite or Parquet output for larger-scale experiments
