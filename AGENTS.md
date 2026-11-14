# NLPU Agent 入口

## 开始任务

1. 阅读 [context 根节点](context/README.md) 和 [审核规则](context/governance/review-policy.md)。
2. 按根节点导航阅读本次任务涉及的正式节点，再核查相关代码及当前工作区。
3. 阅读已批准的 [研究目标](context/purpose/final-goal.md)；其他正式节点缺失时，以代码和项目原始文档为证据，明确区分事实、推断和待用户确认事项。
4. 继续遵守任务目录中更具体的 AGENTS.md；context 不替代用户当前指令或适用的协作规则。

## 知识维护

- Agent 可在 `context/_candidates/` 创建、修订提案和维护待审索引。
- 正式 context 的新增、修改、移动、废弃和删除，须有用户针对具体版本与范围的明确批准。用户已经批准的操作直接执行，不重复请求。
- candidate、被拒绝提案、过期记录和文档中的待确认判断，不能作为已确认的项目意图或约束。
- 发现代码与 context 不一致时，报告差异并提出 candidate；不要自行覆盖正式知识。
- 不把本项目 context、隐藏 gold 或宿主机评估资料擅自注入受控 benchmark 的 Agent 输入。

## 两个 Git 仓库

- NLPU 仓库管理程序及本入口；`context/` 被父仓库忽略，使用独立 Git。
- context 操作使用 `git -C context ...`。程序 commit 与 context commit 分开记录。
- 不覆盖已有程序改动，不自动发起实验、付费模型调用或远程发布。
- 如果克隆后缺少 context，说明缺失并使用原始源码和文档继续可开展的任务；不要假装已读取上下文。
