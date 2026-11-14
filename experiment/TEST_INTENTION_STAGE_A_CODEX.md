# 阶段 A：使用 Plus 订阅补生成

版本：v3，2026-11-09。状态：TI-18 补生成已结束、TI-19 源码审查与本地新版发布已验收。详见[阶段 A 完成报告](TEST_INTENTION_STAGE_A_RESULTS.md)。未启动新的 SDD 定位实验。

用户在讨论 Plus 内含 Codex 后要求“请你继续A的生成”。本轮据此使用本机已登录的 ChatGPT Plus，新增直接 API 费用边界为 0：不使用 DeepSeek／OpenAI API key，不购买额外 credits，不兑换额度重置券，不以 API 作为额度不足时的替代通道。

## 实际运行身份

| 项目 | 当前值 |
| --- | --- |
| CLI | 本机 codex-cli 0.151.0 |
| 登录 | ChatGPT；已读账户计划为 Plus |
| 模型 | 账户当前可用列表的默认模型 `gpt-5.6-sol` |
| 思考配置／速度 | high／标准速度 |
| 提示版本 | source-evidence-intention-codex-1 |
| 输入范围 | 原 22 个公开 base 的 772 个补生成包 |
| 目标覆盖缺口 | 6,274 条版本化测试记录 |
| 成功复用 | 2,593 个旧成功输入包，保留原生成模型与配置 |
| 并发 | 1，按冻结顺序处理 |
| 单次时限 | 600 秒 |
| 新输出 token 上限 | CLI 默认；不宣称沿用 DeepSeek 的 16,384 硬上限 |
| 总调用边界 | 最多 1,544 次 CLI 启动，含模型不可用的首次失败；当前有效计划最多再用 1,543 次 |

最初依据用户配置选择了 gpt-6.1-sol，但服务端返回该账户不支持该模型。该次调用未产生可用描述；失败日志、会话和缺失 usage 原样保留。之后通过 `model/list` 查得实际可用模型，修订为默认的 gpt-5.6-sol。没有覆盖这次失败或把它登记成成功。

前后模型属于独立计划与执行目录。当前有效运行：

- [模型与输入计划](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/plan-v2/plan.json)
- [实际可用模型快照](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/available-models.json)
- [逐包运行状态](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/execution-v2/status.json)
- [自动续接状态](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/continuation/status.json)
- [订阅登录及初始额度检查](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/subscription-preflight.json)

## 输入隔离与校验

Codex 只收到当前输入包：测试源码、明确提供的依赖上下文、未知项与逐测试合法证据 ID。每次使用独立空目录、临时会话、只读 sandbox，关闭项目 AGENTS 读取、记忆、shell、MCP/apps、插件、浏览和多 Agent 功能，以结构化 JSON 输出。

关闭工具后，CLI 在本机保存会话事件、可见最终回复、请求身份和最终 token 用量。出现工具调用会中止生成；本轮没有向生成器提供 PR 标签、已有定位答案或最终补丁。

原严格校验继续生效：完整测试集合、字段、场景和逐测试证据引用都要通过，失败最多修复一次。新缓存身份包含模型、提示、schema 和完整输入；旧成功记录保留自己的生成来源，不伪装成 Codex 生成。

这里记录的是 CLI 启动及最终会话用量，不能将其冒充精确的 provider HTTP 请求计数。CLI 内部网络重试并不完全可见；超时或不明失败保留缺失用量，不自动重发。

## 额度不足时怎样继续

每个包开始前读取订阅额度。任一适用窗口达到 95% 时停止新派发，保留已生成结果。后台续接器只在额度恢复后继续同一计划、同一目录，成功包不会重新生成。

2026-11-06 以前，续接器只处理额度等待，额度查询报错和生成连接超时都可能让后台退出。新版增加 `--resume-transient-errors`，仅在诊断证据满足下面条件时继续：

- 额度查询遇到暂时错误时，每 60 秒重新读取；没有可靠额度信息时不生成。
- 生成请求因连接问题失败或超时后，该包必须已经落为 `FALLBACK` 或 `COST_UNKNOWN`，且请求日志与账本对应。原失败包保持原状态，只继续尚未处理的包。
- 继续前等待 60 秒；如果下一包也失败且期间没有成功生成，则等待 300 秒。连续三次这样的失败且没有成功进展时停止派发，保留诊断。成功生成会重置连续失败计数。
- 有未结束的请求、来源变化、异常工具调用或无法确认原因的错误时停止。不会把连接错误笼统当成可恢复错误。

本次只修改续接器及其测试，不修改冻结的生成器、模型、提示、输入包、600 秒时限或请求总上限。新续接策略、代码哈希、旧文件备份和启动记录保存在原执行根。没有购买 credits 或兑换重置券的代码路径。

初始检查时五小时额度已用约 27%，周额度约 1%，额外 credits 余额为 0。此后额度还会受本聊天和用户其他使用影响，因此不能据此承诺全部生成的完成时间。

## 已经验证的实际产物

首个有效包为 `TestFeedExport.test_export_items_json_field_list`。新记录通过结构、身份及证据引用校验，CLI 报告输入 6,426 token、输出 935 token；缺失的格式 helper 断言明确保留为未知，没有写成已执行成功的结果。

这是首包诊断，不代替 TI-19 的正式质量抽样。实时数量以运行账本为准，不能把本文的首包说明当作当前总进度。

2026-11-06 离线共验证 28 项：原恢复与发布的 15 项、订阅路由／额度保护 2 项，以及续接与异常恢复 11 项。新增测试包含额度查询失败后等待、额度恢复后续跑、用量未知包不重试、日志与请求不匹配时拒绝恢复、异常工具调用和来源错误停止，以及连续失败上限。只读额度查询失败不计入生成失败次数。它们验证执行契约，不证明所有语义描述准确。

## 查进度与接手

下面入口只读，不调用模型：

```bash
python3 -B -m experiment.test_intention.codex_progress \
  --plan /data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/plan-v2 \
  --execution /data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/execution-v2
```

后台续接器的 PID 和命令见 [launch 记录](/data2/wangzuohit/NLPU-experiments/test-intention/stage-a-codex-20261104-v1/continuation-launch.json)。接手先查该进程和续接状态，不重复启动。模型代码与生成计划已经绑定来源哈希；正在运行时不修改这些文件。

## 生成后的工作与比较边界

2026-11-08 全部包已终结，续接器建立了 48 条固定样本并正常结束。2026-11-09 已逐项核对源码：45 条接受、2 条整包隔离、1 条确认无语义。新版 22-base 材料已导出为 `compact-intention-v5` 并通过全量来源与读取验收，保留 104 条静态回退，明确为部分覆盖。续接器没有自动填写“全部接受”；具体结论与证据见[完成报告](TEST_INTENTION_STAGE_A_RESULTS.md)。

新材料会混合原 DeepSeek 成功描述与新 Codex 描述。生成模型、提示和分包都已变化，因此不能将它与旧材料的差值称为纯粹的覆盖收益。TI-14 的后续 B/C 比较仍以材料可用性的整体影响为问题；执行前需写入实际覆盖、质量抽样与两种生成来源。

原 DeepSeek 费用估算保留在[阶段 A 离线交付](TEST_INTENTION_STAGE_A.md)，仅作为未执行的 API 备选方案；本轮不再等待那笔新增 API 额度。
