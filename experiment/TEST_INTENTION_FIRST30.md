# 测试行为表示：首批 30 个 PR 实验

日期：2026-11-01。分支：`experiment/test-intention`。

用户已明确授权实际运行。目标是检查：在原方案一的仓库中增加测试行为材料，是否能够找回更多需要更新的已有测试。

当前状态：首批 90 项已全部终结并完成比较，整体指标下降。26 项成功封存，64 项因共享 token 预算耗尽而失败。结果与诊断见 [首批结果](TEST_INTENTION_FIRST30_RESULTS.md)。

## 比较什么

原组直接复用 `round-65f66ff1426e4c7d1f8da662`，不重跑模型。新组使用原首批配置 `scrapy-30pr-testcase-v1.json` 的 PR 和对应 base，运行 OpenSpec、Spec Kit、cc-sdd，共 90 项 Detect。原组失败保留为零分；无正例任务另列；证据损坏或标签不完整时停止正式比较，不能缩小分母后报告提升。

输入仍是原 title/body 与实现前的仓库。表示生成只读取允许的 base 源码；不接触本次实现 diff、最终测试补丁、隐藏答案或旧组预测。新增材料不预选候选测试，也不引入方案二的生产代码定位。

待 90 项全部终结并保存封存证据后，再在宿主机评价。核对两组每项的测试清单和标签校验码、完整配对身份以及可计分集合。报告方法级 macro/micro precision、recall、F1，失败数量和逐 PR 变化。重点观察 recall，并同时检查误报是否增加。本实验输出不固定 top-k，因此不将它冒充 Recall@200 比较。

原历史配置只固定了同一模型配置路径，未能独立证明当时每项实际读取的模型配置字节与当前完全一致。比较报告应保留这一历史证据局限。

## 新材料怎样形成

22 个不同 base 分别从源码构建 JSON，合计 53,249 条“版本内测试方法”记录；按完整输入去重后共 3,277 批，输入合计约 7,773 万 JSON 字符。最大单批 60,191 字符。每个测试保留原 `path::qualified_name` 身份、原源码和来源位置、静态事实、共享准备代码与依赖、模型解释和不确定项。宿主机核对测试身份与原 inventory 完全一致，不删除难以解释的测试。

共享上下文的小组每批最多 8 个测试、64,000 个 JSON 字符。直接依赖最多展开两层，共享上下文限 24,000 字符；省略内容明确说明并保留校验码。包括测试和已展开 helper 的模块配置、类配置及初始化定义，避免 helper 没改但其配置已改时误用缓存。超大单个测试不继续扩大调用，保留静态表示。

模型使用 `deepseek-flash`、`high`，每次输出上限 16,384 token（含推理）。格式、身份和来源引用校验失败最多修复一次；请求失败或未完成不自动重试。每次调用前先保存请求与费用预留；中断后不能重复发送已开始但未完成记账的请求。

生成阶段最多 4,000 次请求，按峰时输入 2 元／百万 token、输出 8 元／百万 token 保守计账，上限 200 元；输入预留用字节数作保守上界，收到 usage 后更新。未知费用继续占用预留。这是停止边界，不是实际花费。价格依据 2026-11-01 核查的 [官方价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)，实际账单可能受缓存和时段优惠影响。生成与 Detect 成本分别记录。

模型请求只接收源码证据包，不提供工具或仓库访问。JSON 是正式数据；Markdown 为每个测试文件列出行为目录，便于 SDD 阅读。依赖关系单独存储，并列出共享依赖组及模型使用相同操作描述的测试组，方便探索跨测试关系。后者只是模型解释的线索，不代表语义等价或必须一起修改。文件索引保留类分组和模块函数。每个 base 的同一份冻结材料提供给三个 SDD。

## 怎样运行和保存

所有大产物位于：

```text
/data2/wangzuohit/NLPU-experiments/test-intention/first30-v1/
```

`scope.json` 固定 90 项范围、来源及原工作区改动摘要；`static/`、`packets/`、`generation-cache/` 分别保存静态记录、实际输入包和生成结果。`generation-cache/requests/` 保存请求状态与 usage，不保存凭据。`representations/` 是提供给新仓库的材料。

`execution-root/` 是 data2 上独立的执行根目录。只复制冻结依赖并核对哈希，所有新工作区在此准备；历史轮次不改写。表示按内容哈希存储，避免后续构建覆盖旧轮次来源。

依次执行：

```bash
python3 -m experiment.test_intention.pipeline inputs
python3 -m experiment.test_intention.pipeline generate
python3 -m experiment.test_intention.first30 mirror
python3 -m experiment.test_intention.first30 prepare
python3 -m experiment.test_intention.first30 run
python3 -m experiment.test_intention.first30 compare
```

`prepare` 的容器与隔离检查串行完成后才启动 Detect。运行时三个 SDD 可并行，同一 SDD 的 PR 串行，避免固定子网冲突。Detect 沿用原管线，单项超时 45 分钟。本轮实际运行配置开启 100,000 token 的 rollout 预算；此前仅检查模型 profile 而漏记了总配置中的该项，已在结果中补正。先把启动状态持久写入 ledger，才允许模型执行；失败不自动重跑，全部 90 项终结后才能比较。

`prepared-reference.json` 保存冻结轮次入口；`terminal-targets.json` 保存完整终结屏障；`host-comparison/` 保存宿主机评价及差值，包含敏感评价资料，不能送入 SDD 或表示生成输入。

## 已完成的验证

- 12 项新静态解析／生成合成检查通过，覆盖身份、嵌套定义、别名、fixture、共享模块与类配置变更、分支候选、缓存、引用校验、修复和中断请求。
- 新 bundle 校验与既有 round/testcase 兼容共 23 项检查通过。
- `bin/check-testcase` 原有离线验收 95 项通过，不调用模型或 Docker。
- 独立审查用真实 Ledger/schema 和合成 90 项假 Detect 检查三队列；90 次调用前都已有持久的启动状态。

上述检查说明实现具备运行条件，不等于表示内容完全正确或定位指标已有改善。真实运行的成功数、回退数、费用、定位结果和限制在完成后补充。

首次生成中的只读内容抽查覆盖 10 批、58 个测试，仅将生成文字与同批源码证据对照。没有发现明显断言遗漏或预期值改写。两项 contract hook 错误测试的摘要使用了比现有证据更强的因果措辞；保留原始模型解释，并将其视为局限。该抽查不涉及隐藏答案，不代替全量语义正确性验证。

第一版的边界：静态记录列出调用、赋值、条件、断言及可见的变量联系，没有恢复 Python 的所有执行路径。对象来源有分支时保留多个候选。每个方法中的场景由模型结合原源码解释；这些描述需要核查，不能视作形式化证明。共享操作组也只是探索测试关系的入口。

实际生成期间由 `continue_first30` 控制器等待生成完成，再依次发布材料、同步执行代码、prepare、run、compare。状态保存在产物根目录的 `execution-status.json`，各阶段出现异常即停止后续阶段；不会因为进程已启动就报告实验完成。
