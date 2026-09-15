# 输出文件字段说明（schema v3）

本项目同时保留方法级实验产物和原有文件级兼容产物。方法级模型输入是 `output/prompt/`；`output/raw_prs/` 含隐藏 gold，只能用于数据构建和验证。

| 文件 | 生成方 | 说明 |
|------|--------|------|
| `dataset.jsonl` | demo_pipeline | 数据集样本（代码 diff + 自然语言描述） |
| `prompts.jsonl` | demo_pipeline | 旧文件 diff prompt；可能泄漏测试变更，不用于方法级主实验 |
| `quality_report.json` | demo_pipeline | 数据集质量统计 |
| `raw_prs/<owner>__<repo>.jsonl` | collector + method mining | 完整 PR 记录、方法配对与隐藏 gold |
| `raw_prs/manifest.json` | collector + method mining | 采集元数据和方法挖掘计数 |
| `prompt/<owner>__<repo>.json` | build_prompts | 无 gold 泄漏的方法级模型输入 |
| `prompt/manifest.json` | build_prompts | prompt 来源、字段与数量 |

---

## 1. dataset.jsonl（旧文件级兼容产物）

每行一个 JSON 对象，一个「变更的 Python 文件」对应一条样本。它是
「代码片段 + 自然语言描述」的对齐结果，可直接用于训练或喂给 LLM 生成测试用例。

### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `repo` | string | 仓库全名，如 `psf/requests` |
| `pr_id` | int | PR 编号 |
| `filename` | string | 变更的 Python 文件路径 |
| `fragment_type` | string | 代码片段粒度，当前固定为 `file`（预留后续 AST 级扩展） |
| `filter_reasons` | list[string] | 三维过滤的判定理由，`+` 开头表示通过 |
| `annotations` | object | 软标注（不参与过滤），见下方说明 |
| `diff_hunks` | list[string] | 该文件的 unified diff，按 `@@` hunk 拆分 |
| `nl_title` | string | 清洗后的 PR 标题 |
| `nl_body` | string | 清洗后的 PR 正文 |
| `nl_comments` | string | 清洗后的评论（讨论评论 + 行内 review 评论，用 ` \| ` 拼接） |
| `nl_commits` | string | 清洗后的提交信息（用 ` \| ` 拼接） |
| `nl_description` | string | 主描述 = `title + body` |
| `nl_description_extended` | string | 扩展描述 = `description + commits + comments` |

### annotations 字段（软标注）

| 字段 | 类型 | 说明 |
|------|------|------|
| `has_test_changes` | bool | 该 PR 是否修改了测试文件 |
| `closes_issue_count` | int | 该 PR 关联（关闭）的 issue 数量 |
| `title_words` | int | 标题词数 |
| `body_words` | int | 正文词数（清洗后） |
| `commits_words` | int | 提交信息总词数（清洗后） |

---

## 2. prompts.jsonl（旧文件级兼容产物）

每行一个 JSON 对象，一条可直接上传给 LLM 的 test-case 生成 prompt。

| 字段 | 类型 | 说明 |
|------|------|------|
| `repo` | string | 仓库全名 |
| `pr_id` | int | PR 编号（用于溯源） |
| `filename` | string | 变更的 Python 文件 |
| `prompt` | string | 组装好的 prompt，内容结构如下 |

`prompt` 字段内部结构（由 `TEST_CASE_PROMPT_TEMPLATE` 填充）：

```
You are an expert Python test engineer.

Given the code change (unified diff) and its natural-language description below,
write runnable pytest test cases that verify the change.

Repository: {repo}
Changed file: {filename}

Natural-language description:
{nl_description_extended | nl_description}

Code change (unified diff):
{diff_hunks 拼接}

Write the test cases now. Return only Python code, no explanation.
```

其中 `{description}` 优先取 `nl_description_extended`，为空时回退到
`nl_description`；`{diff}` 由 `diff_hunks` 列表拼接还原成完整 diff。

---

## 3. quality_report.json

| 字段 | 类型 | 说明 |
|------|------|------|
| `sample_count` | int | 样本总数 |
| `unique_sample_count` | int | 去重（repo+pr_id+filename）后的样本数 |
| `with_test_changes` | int | 含测试文件改动的样本数 |
| `with_closing_issues` | int | 关联 issue 的样本数 |
| `empty_text_count` | int | `nl_description` 为空的样本数 |
| `empty_extended_text_count` | int | `nl_description_extended` 为空的样本数 |
| `empty_hunks_count` | int | `diff_hunks` 为空的样本数 |

---

## 4. raw_prs/<owner>__<repo>.jsonl

每行是一条 PR 记录，由 collector 采集，并由 method mining 原地补充。写入采用临时文件原子替换。

| 字段 | 类型 | 说明 |
|------|------|------|
| `repo`, `pr_id`, `pr_url` | string/int/string | 仓库、PR 编号与溯源 URL |
| `merged`, `merged_at` | bool/string | 是否合并及合并时间 |
| `base_sha`, `head_sha`, `merge_commit_sha` | string | checkout PR 前后完整源码所需 revision |
| `ci_status`, `ci_source`, `ci_rollup_state` | string/string/string? | head CI 的归一化结果及来源 |
| `title`, `body`, `changed_files`, `comments/commits/issue refs` | mixed | 原始 PR 内容；方法提取不依赖可能截断的 `patch` |
| `mining_status`, `mining_reasons` | string/list[string] | `not_mined`/`skipped`/`failed`/`no_eligible_pairs`/`mined` 及原因 |
| `method_test_pairs` | list[object] | 候选 test-focal 配对；同时保留 accepted 和 rejected 供诊断 |

每个 `method_test_pairs[]` 包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `sample_id` | string | 由 repo、PR、test node 和 focal node 稳定计算的样本 ID |
| `focal_method` | object | focal 文件/名称、before/after source、hash、调用和 import 信息 |
| `test_change` | object | test 文件/名称、`old_test`、隐藏 `gold_test`、hash、调用和 import 信息 |
| `pair_score`, `pair_confidence`, `pair_evidence` | int/string/list[string] | 配对分数、置信度和证据 |
| `ambiguous_candidates` | list[string] | 最高分并列的 focal node；非空时拒绝 |
| `gold_validation` | object | `gold_on_head`、证据来源及 gold 是否引用 focal method |
| `eligibility`, `rejection_reasons` | string/list[string] | `accepted`/`rejected` 与具体理由 |

`gold_test` 是开发者最终合并到 head 的真实更新测试，只允许保留在 raw 记录中。

---

## 5. prompt/<owner>__<repo>.json

JSON 数组，每项是一条可发送给 OpenSpec/LLM 的方法级 test update 输入，只从 `eligibility=accepted` 且 test `change_type=modified` 的配对生成。

| 字段 | 类型 | 说明 |
|------|------|------|
| `repo`, `pr_id`, `sample_id` | string/int/string | 样本溯源标识 |
| `focal_file`, `focal_qualified_name` | string | PR 后 focal method 的位置与限定名 |
| `focal_method_after` | string | 模型可见的 PR 后 focal method 完整源码 |
| `old_test_file`, `old_test_qualified_name` | string | PR 前旧 test 的位置与限定名 |
| `old_test` | string | 模型需要更新的 PR 前 pytest test 源码 |
| `pair_confidence`, `pair_evidence` | string/list[string] | 配对置信度与可审计证据 |
| `prompt` | string | 要求只返回更新后 Python test code 的完整提示词 |

可通过 `--keep-fields` 加入 `nl_description` 或 `nl_description_extended`。

构建器禁止输出 `gold_test`、`gold_patch`、`test_diff`、`focal_method_before` 和 `before_source`。

---

## 6. manifest 文件

`raw_prs/manifest.json` 记录 schema v3、各仓库的 PR 数量，以及 pair/accepted/mined/failed 数量。`prompt/manifest.json` 的字段如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version`, `mode` | int/string | 当前为 `3` 和 `method`（旧模式为 `file`） |
| `generated_at`, `source_files` | string/list[string] | 生成时间与输入 raw 文件 |
| `raw_pr_count`, `kept_pr_count`, `prompt_count` | int | 输入 PR、产生样本的 PR 与最终 prompt 数量 |
| `keep_fields` | list[string] | 每条 prompt 实际保留的字段 |
| `prompt_files`, `prompt_counts` | object | repo 到输出文件及数量的映射 |

## 7. 验证语义

- `gold_on_head=pass`：当前表示该 merged PR 的 head CI rollup 为 success，来源为 `pr_ci_rollup`。
- `gold_references_focal=true`：coverage、直接静态调用或最多三层的静态调用路径能够连接 gold test 与 focal method。
- accepted：test 必须是 base/head 均存在的 modified pytest test；存在上述行为证据、没有最高分并列，并且 PR head CI 成功。
- `module_import`、`name_overlap` 和 `diff_proximity` 只帮助排序，不能单独满足 focal-reference 验证。
