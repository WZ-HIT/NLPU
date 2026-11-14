# P2完成记录：新增事实已交付，关系扩展暂缓

2026-11-03，分支`experiment/test-intention`。TI-09实现及离线验收完成；TI-10完成来源与可达案例审查，按条件暂缓新增关系扩展。**本次收益有限：相同6,000字节首屏预算下，目标命中从P1的24个增加到25个，尚未解决大批量更新任务。**没有模型调用，没有重跑旧定位流程。

## 交付内容

| 项目 | 交付 | 保留的限制 |
| --- | --- | --- |
| TI-09 | 类型注解、继承来源、有限关联上下文调用、所引用的导入、外层条件五类事实；短搜索、match和源码回查 | 静态候选不证明执行、运行时类型或修改必要性；动态绑定、完整MRO、完整导入解析和资源生命周期未建模 |
| TI-10 | 既有关系与新增继承的两次审查、源码样例、低连接度限制及暂缓决定 | 当前案例是首屏遗漏，未证明需要扩展原匹配集合；不自动加入邻居，不新增关系排序工具 |

新包为`compact-intention-v4`，覆盖原22个base、53,249条版本化测试，其中46,975条GENERATED、6,274条STATIC_FALLBACK。原证据数据库与P1逐字节一致，原语义、条件／动作／预期场景和未知项都保留。新事实独立储存，每个base内去重，累计259,972条版本化事实；同一源码在不同base重复出现，不视为独立研究样本。

| 新字段 | 有非空事实的测试记录数 | 搜索和回查内容 |
| --- | ---: | --- |
| annotations | 22,919 | 参数、返回值、局部变量注解；字符串注解只当语法处理 |
| inheritance | 17,580 | 基类表达式、所属类、静态来源链和未解析项 |
| context_calls | 46,764 | 原证据已关联的初始化、fixture或直接helper定义内部调用 |
| imports | 52,486 | 上述作用域引用到的别名及完整导入名候选；保留条件和遮蔽疑点 |
| guards | 24,585 | 定义外层、所用导入分支的条件；不判断真假和分支方向 |

上下文每测试最多4个定义、每定义最多16次调用。按测试关联累计省略2,379个定义、7,670次调用，具体记录在coverage中；这些不是互不重复的源码数量。新字段权重统一固定为1，没有按PR或标签调整。完整新包累计约1.79 GB，默认搜索输出仍限制为6,000 UTF-8字节，不据磁盘或读取字节推算provider token。

## 30PR的固定预算结果

[比较设计](TEST_INTENTION_P2_DESIGN.md)先固定字段、上限与比较组。公开查询直接复制P1，逐字节相同；保留原29个正例PR／361个目标，以及1个无正例PR。排名与页面先封存，再由宿主机评价。该开发集在此前诊断中已经见过，不称为盲测或泛化证据。

| 组 | 材料 | 首屏命中 | 宏平均召回 | 微平均召回 | 全部匹配集合覆盖目标 |
| --- | --- | ---: | ---: | ---: | ---: |
| P | 冻结的P1 R | 24/361 | 37.64% | 6.65% | 151/361 |
| N | P1＋五类新事实 | 25/361 | 38.79% | 6.93% | 181/361 |
| A | P1＋annotations | 24/361 | 37.64% | 6.65% | 151/361 |
| C | P1＋其他四类新事实 | 25/361 | 38.79% | 6.93% | 181/361 |

每组均为一次OR查询、6,000 UTF-8字节、最多25个分页单元；只计完整可见测试，分片完整后才计数。字段组分别计算词频统计，消融组代表只索引相应新字段的离线条件。它们不是不同Agent策略的模型试验。

N相对P只有PR7918增加1个首屏命中，其他29PR的命中数相同，没有下降PR。PR7918的原匹配集合已经含有这个目标，新事实条件下它进入首屏第6位；因此这1个增量属于排序／展示收益，不能称为新增目标进入了匹配集合。新增字段与词频统计同时变化，当前消融不足以把收益归给某一个字段。

集合覆盖增加30个目标：宏平均集合覆盖从78.82%到83.72%，微平均从41.83%到50.14%。但首屏只增加1个，说明“找到更多可能候选”尚未充分转化为“先读到正确候选”。A组在当前指标上没有收益；不能由此断言注解在其他查询或任务上没有价值。

## 预先声明的复杂任务检查

分组按公开文本关键词固定，仅用于解释，不用于运行时选字段或加权。类型关键词组包括Content-Type这样的非类型注解任务，因此只是关键词组，不当作人工确认的任务分类。

| 公开关键词组 | 正例PR数／目标数 | 匹配集合覆盖：P→N | 首屏命中：P→N |
| --- | ---: | ---: | ---: |
| 类型关键词 | 3／128 | 96→118 | 0→0 |
| 构造或类结构关键词 | 2／178 | 13→16 | 2→2 |
| 其他 | 24／55 | 42→47 | 22→23 |

关键任务仍然困难：

- PR7968：100个目标的集合覆盖从87到100，但首屏仍为0。当前证据更支持检查排序与阅读策略，不能再把这一任务的首屏失败简单归为缺少可检索事实。
- PR7808：175个目标只从覆盖10个增加到13个，首屏仍为0。已有事实及本次有限上下文提取仍不能覆盖大多数目标；本次没有定位到足以解释全部缺口的单一根因。

因此，TI-09完成的是事实提取、来源与阅读能力；**没有证明预期复杂任务的首屏召回已经改善。**唯一新增首屏命中发生于其他关键词组，不能夸大为类型或构造任务的成功。

无正例PR8067单列：N首屏有10条候选，匹配集合由1,700扩大到2,179。这不是正确空预测，检索候选也不等于最终误报。对固定每查询第一条结果的命中证据回查，N平均1次调用、约555字节，P约559字节；不代表Agent完整调查成本或token节省。

## 为什么暂缓关系扩展

[关系审查与样例](TEST_INTENTION_P2_RELATION_REVIEW.md)详细区分了已有fixture／初始化、弱共享调用及新增继承。固定P1首屏前4个种子、每关系连接2～12个测试时，没有找出位于原匹配集合外、且通过当前审查条件的正例。

PR8022、PR7986、PR8002有可解释的首屏可达案例，但候选本已匹配，而且是同文件、同类方法。这支持后续研究组内导航或排序；尚不支持本阶段新增默认关系候选。暂缓是有限范围的实施决定，不能推论关系方法普遍无效，也没有用neighbors调用次数作判断。

## 验收与复现

产物目录：[p2-20261103-v1](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1)。

- [覆盖清单](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/coverage.json)、[22包清单](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/bundles.json)：测试身份、状态及原证据一致，source_files与原纯base清单逐项校验。
- [逐条源码复核](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/source-verification.json)：259,972条版本化去重事实全部验证原文片段、UTF-8字节列位置、文件SHA与事实ID；逐测试覆盖及成员引用完整。
- [查询封存](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/query-seal.json)、[排名封存](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/rankings-seal.json)、[逐PR指标](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/offline-metrics.json)、[CSV](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/per-pr.csv)：保留全部120组排名和页面，标签源与P1一致，未访问68PR独立测试标签。
- [独立复核](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/verification.json)：独立重组120份页面并重算宏／微召回；实际运行30条冻结包N搜索命令，内容和字节量与封存结果一致；22包通过宿主机清单校验。
- [相关测试](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/related-tests.log)：61项通过，其中10项为新增P2检查，覆盖嵌套作用域、未执行项目、局部遮蔽、条件导入、继承循环／外部基类、截断披露、Unicode来源和新增数据库／代码变化后的旧游标拒绝。
- [原离线验收](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/acceptance.log)：95项、5/5组通过；与相关测试有重叠，不相加称为独立样本。
- [容器检查](/data2/wangzuohit/NLPU-experiments/test-intention/p2-20261103-v1/runtime-probe.json)：1个固定既有镜像，在原AppArmor/seccomp、bubblewrap、UID1007、只读挂载、网络none下，搜索／match／原base源码哈希检查成功；未挂载模型凭据。其余命令检查在宿主机执行。

实现入口：[提取器](test_intention/maintenance_static.py)、[只读视图](test_intention/maintenance_view.py)、[导出](test_intention/p2_bundle.py)、[离线比较](test_intention/p2_offline.py)、[独立复核](test_intention/p2_verify.py)。Agent包只包含公共阅读代码与base派生材料，不包含宿主机评价或关系诊断脚本。

新实验可显式选择`compact_pilot.setup(..., representation_root=新目录/representations)`；原默认输入和历史执行根未切换。`batch/stages.py`已识别v4，并提示按需读取新事实。

```bash
python3 test-intentions/read.py search --query keyword --search-field maintenance.annotations
python3 test-intentions/read.py maintenance 'TEST_ID' --field inheritance
python3 test-intentions/read.py match 'TEST_ID' --ref '/maintenance/annotations/0/text'
python3 test-intentions/read.py source 'TEST_ID' --ref 'maintenance:FACT_ID'
```

这些结果是开发集的单页候选检索比较，不是最终Detect输出。SDD完成率、最终P/R/F1与provider token成本仍待TI-12b；本阶段不因离线多1个命中而自动启动模型实验或改写研究结论。
