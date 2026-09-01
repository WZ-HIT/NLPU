# 输出文件字段说明

本目录（`output/`）由 `demo_pipeline.py`（配合 `collector/`）生成，包含以下文件：

| 文件 | 生成方 | 说明 |
|------|--------|------|
| `dataset.jsonl` | demo_pipeline | 数据集样本（代码 diff + 自然语言描述） |
| `prompts.jsonl` | demo_pipeline | 面向 LLM 的 test-case 生成 prompt |
| `quality_report.json` | demo_pipeline | 数据集质量统计 |
| `raw_prs/<owner>__<repo>.jsonl` | collector | 采集的原始 PR 记录 |
| `raw_prs/manifest.json` | collector | 采集元数据（schema 版本、计数） |

---

## 1. dataset.jsonl

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

## 2. prompts.jsonl

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

## 4. raw_prs/<owner>__<repo>.jsonl（由 collector 生成）

采集阶段的原始 PR 记录，每行一个 JSON 对象。字段见
`collector/models.py` 中的 `PullRequestRecord`：`repo`、`pr_id`、`title`、
`body`、`merged`、`ci_status`、`language`、`changed_files`（含 `patch`）、
`comments`、`review_comments`、`commit_messages`、`commit_issue_refs`、
`body_issue_refs`、`closing_issue_refs`。
