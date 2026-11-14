# 一次 TI 搜索与候选判断的演示

日期：2026-11-10。

**这是一个虚构 PR 配合真实 TI 材料的教学演示，不是实际 PR 的预测或评价结果。** 查询、排序、测试卡片、场景及源码来自当前 C 组材料的实际读取；PR 要求和最终选择是为说明流程而设置的演示内容。

使用公开 base `3857c6906b2da51e12ca6005434512b7704fd659`。本次只读材料和源码，没有调用模型、读取隐藏标签、修改实验输入、保存正式候选调查记录或提交定位结果。

## 1. 假设 Agent 收到的 PR

标题：调整重定向次数耗尽时的异常类型。

正文：超过最大允许重定向次数时，改为抛出 `ValueError`；`redirect_ttl` 耗尽时继续抛出 `IgnoreRequest`。重定向计数字段和其他行为保持原约定。

据此需要区分两个情况：超过最大次数的测试可能需要修改；单独验证 TTL 耗尽的测试不能仅因为同样包含 redirect 就选中。

## 2. 第一次查询：没有命中

Agent 先尝试配置名称：

```bash
python3 test-intentions/read.py search --query REDIRECT_MAX_TIMES
```

实际返回：

```json
{
  "items": [],
  "matched_test_count": 0,
  "returned_complete_test_count": 0,
  "next_cursor": null
}
```

以上只摘录与本步骤有关的返回字段。结果说明这次字面查询未匹配当前索引，不能据此判定没有相关测试。

## 3. 更换查询词：找到 5 条结果

Agent 改用两个更宽的词，要求两者都命中：

```bash
python3 test-intentions/read.py search \
  --query redirect --query times --mode and --limit 3
```

读取器实际找到 5 条，本页返回前 3 条：

| 顺序 | 测试限定名 | score | 行为目标译述 |
| --- | --- | ---: | --- |
| 1 | `TestRedirectBase.test_max_redirect_times` | 208.74311960 | 检查重定向计数，以及超过最大次数时抛出 IgnoreRequest |
| 2 | `TestRedirectBase.test_ttl` | 147.49399287 | 检查 TTL 为 1 时允许一次重定向，再处理时抛出异常 |
| 3 | `test_reports_all_found_keys` | 134.13847179 | 检查警告文本报告 retry_times 和 redirect_times |

表格为真实搜索结果条目的选取字段，行为目标原文为英文，表中译述用于解释。前两条位于 `tests/utils/bases/redirect.py`，第三条位于 `tests/test_spidermiddleware_metacopy.py`。

第一条结果的代表性命中字段是 `identity`，`matching_fields` 为 11。说明搜索到了多个相关字段，但仍需读取源码判断是否需要修改。相关性最高也不是正确答案的保证。

此时 `matched_test_count` 为 5，`returned_complete_test_count` 为 3，`next_cursor` 非空。Agent 目前只看到 3 条，不能把它们当成全部结果。

## 4. 翻页：看完这次查询的匹配集合

Agent 继续使用同样查询和选项，带上上一次返回的游标：

```bash
python3 test-intentions/read.py search \
  --query redirect --query times --mode and --limit 3 \
  --cursor '上一页实际返回的 next_cursor'
```

这次实际返回剩下 2 条：

| 顺序 | 测试限定名 | score | 行为目标译述 |
| --- | --- | ---: | --- |
| 4 | `test_skip_keys_setting_partial` | 122.06821726 | 跳过 retry_times 后，警告仍包含 redirect_times |
| 5 | `TestEngineDownloadAsync.test_download_async_many_redirects` | 4.10136692 | 验证较长请求替换链能够完成并返回最终响应 |

本页 `next_cursor` 为 null，表示这次查询的 5 条结果已经返回完毕。**这只表示当前查询已翻完，不表示整个仓库的相关测试全部找到。** 真实定位中仍应根据任务范围和证据缺口决定是否继续换词或搜索源码。

## 5. 读取第一个候选的测试卡片

Agent 判断第一条最值得调查，调用：

```bash
python3 test-intentions/read.py show \
  'tests/utils/bases/redirect.py::TestRedirectBase.test_max_redirect_times'
```

实际测试卡片包含：

| 字段 | 本次返回内容 |
| --- | --- |
| `status` | `GENERATED` |
| `location` | `tests/utils/bases/redirect.py`，72～82 行 |
| `goal` | `Checks redirect count tracking and IgnoreRequest when max_redirect_times is exceeded.` |
| `inputs` | 最大次数设置为 1；创建请求；重定向目标为 `/redirected` |
| `scenarios.total` | 2 |
| `scenarios.more` | 1 |
| `scenarios.read` | 提供 `scenarios TEST_ID` 读取入口 |
| `uncertainty_count` | 4 |

场景预览只显示了“第一次重定向成功、计数为 1”，尚未显示超过次数的场景。恰好后一个场景才与虚构任务有关，因此这次有理由继续读取完整场景。

卡片还显示了 autouse fixture `fast_engine_heartbeat`。本例没有证据表明它影响异常类型，因此没有继续展开这个 fixture。可见依赖不要求全部阅读。

## 6. 展开相关场景

```bash
python3 test-intentions/read.py scenarios \
  'tests/utils/bases/redirect.py::TestRedirectBase.test_max_redirect_times'
```

实际完整语义意图的第二个场景说明：

- 条件：已有重定向请求的 `redirect_times` 等于最大允许次数。
- 动作：在 `pytest.raises(IgnoreRequest)` 中再次调用 `process_response`。
- 预期：抛出 `IgnoreRequest`。
- 证据：该测试自身及其允许关联定义的 ID。

到这里，Agent 获得了一个待核实的对应关系：PR 要改最大次数耗尽时的异常，而该场景仍描述旧异常。接下来需要核对源码，不能只依据模型生成的场景直接选择。

## 7. 直接回查源码，并按返回偏移继续读取

```bash
python3 test-intentions/read.py source \
  'tests/utils/bases/redirect.py::TestRedirectBase.test_max_redirect_times'
```

默认每次最多 8 个输出单位，第一次只返回源码 72～79 行，同时返回 `next_offset: 8`。关键的异常断言尚未显示，因此继续读取：

```bash
python3 test-intentions/read.py source \
  'tests/utils/bases/redirect.py::TestRedirectBase.test_max_redirect_times' \
  --offset 8
```

两次结果合起来得到完整方法：

```python
def test_max_redirect_times(self):
    self.mw.max_redirect_times = 1
    req = Request("http://a.example/302")
    rsp = self.get_response(req, "/redirected")

    req = self.mw.process_response(req, rsp)
    assert isinstance(req, Request)
    assert "redirect_times" in req.meta
    assert req.meta["redirect_times"] == 1
    with pytest.raises(IgnoreRequest):
        self.mw.process_response(req, rsp)
```

现在可以确认：异常断言直接写在该测试方法中。对于虚构任务明确限定的“最大次数耗尽”场景，当前方法预期与新要求不一致，修改共享 helper 也不能消除方法中显式写出的旧异常类型。这支持选择该方法。

这条路径直接读取源码，未要求先调用 `sensitive`、`point` 或 `facts`。它们都是可用的读取方式；已经取得当前需要的源码依据，就不必为凑齐步骤重复调用。

## 8. 检查其余命中，区分相关与需要修改

本次也实际读取了其余四个方法的源码，用于说明演示中的排除依据。

| 候选 | 源码中确认的事实 | 对虚构任务的演示判断 |
| --- | --- | --- |
| `TestRedirectBase.test_max_redirect_times` | 最大次数设置为 1，超过后显式要求 `IgnoreRequest` | 选择：方法内异常预期与任务冲突 |
| `TestRedirectBase.test_ttl` | 最大次数设置为 100，请求的 `redirect_ttl` 为 1，检查 TTL 耗尽 | 排除：虚构任务明确保持 TTL 异常约定 |
| `test_reports_all_found_keys` | 构造包含 `retry_times`、`redirect_times` 的请求并检查警告文本 | 排除：任务未改变这些键名或警告约定 |
| `test_skip_keys_setting_partial` | 检查跳过某些 meta 键后警告仍报告剩余键 | 排除：任务未改变键过滤及警告行为 |
| `TestEngineDownloadAsync.test_download_async_many_redirects` | mock 下载器返回请求链，检查最终响应和调用次数 | 排除：当前方法没有核对最大次数耗尽时的异常 |

这些判断只对应本例的明确假设，不是实际 PR 的结论，也没有与隐藏标签核对。若真实任务描述的范围更宽或兼容性不清楚，就需要进一步阅读，不能照搬这张表。

## 9. 形成候选调查记录

模拟 Agent 会为实际调查的测试分别记录判断。例如第一个候选：

| 内容 | 演示记录 |
| --- | --- |
| 测试 ID | `tests/utils/bases/redirect.py::TestRedirectBase.test_max_redirect_times` |
| 任务要求 | 最大重定向次数耗尽时改为抛出 ValueError |
| 状态 | `selected` |
| 修改范围 | 现有测试方法内容 |
| 方法修改理由 | 方法内显式要求 IgnoreRequest，与新要求冲突 |
| 支持依据 | 73 行固定最大次数为 1；81～82 行断言耗尽后的异常 |
| 反对依据 | 本例已读方法中未见能消除该冲突的条件 |
| 不确定项 | 这一次查询是否覆盖整个任务所需方法，仍不能据此保证 |

这里展示的是记录内容说明，没有向正在运行的实验规划目录保存记录。

## 10. 模拟正式输出与结束条件

如果教学例子只要求处理本次查询的 5 个候选，最终结果示意如下：

```json
{
  "candidates": [
    {
      "path": "tests/utils/bases/redirect.py",
      "symbols": ["TestRedirectBase.test_max_redirect_times"],
      "reason": "方法内断言最大重定向次数耗尽时抛出 IgnoreRequest，与任务要求的 ValueError 不一致。"
    }
  ]
}
```

真实定位任务需要再确认任务范围内是否还有遗漏，完成对应 SDD 规划，按公共契约保存、校验和提交。结构与身份校验不判断更新必要性，也不证明搜索召回完整。

本文件没有实际提交这份示意 JSON，没有生成真实定位指标。它演示完成的是：**一次查询尝试、一次改写后的分页搜索，以及这 5 个命中的证据阅读和候选判断。**

## 本次实际使用与跳过的读取操作

| 操作 | 本例是否使用 | 原因 |
| --- | --- | --- |
| 搜索及更换查询 | 使用 | 第一次字面查询没有命中 |
| 搜索翻页 | 使用 | 共匹配 5 条，第一页只返回 3 条 |
| 测试卡片 | 第一个候选使用 | 了解场景及其未展示数量 |
| 完整场景 | 第一个候选使用 | 与任务直接相关的第二个场景未显示 |
| 测试源码及源码翻页 | 使用 | 核对方法内的断言与实际场景 |
| 完整行为目标 | 未另外读取 | 当前显示内容已足以引导源码核对 |
| 源码敏感点与事实展开 | 调查路径不需要 | 已直接读取源码；演示准备时另试读了敏感点目录，没有据此补充判断 |
| fixture、helper 及关系展开 | 未使用 | 已取得方法内直接异常断言，当前没有必须通过这些定义解决的问题 |
| 模型调用、正式记录保存和结果提交 | 未执行 | 本次是只读教学演示 |

通用步骤与执行要求见[当前 TI 结构说明第 3.2 节](TEST_INTENTION_CURRENT_STRUCTURE_AND_ABC.md)。
