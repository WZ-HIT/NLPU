# P1完成记录

2026-11-03。TI-08→TI-06→TI-07的实现、22个base产物和离线验收已完成，工作位于`experiment/test-intention`分支。本次没有模型调用，没有重跑旧定位流程；TI-12b的模型评价和P2仍未执行。

## 已完成的内容

| 任务 | 实际变化 | 可核对的产物 |
| --- | --- | --- |
| TI-08 | 将已有调用、断言、赋值、条件、mock、参数化、直接依赖与身份字段纳入检索；保留模型解释与静态候选的区别 | [字段与比较契约](TEST_INTENTION_P1_DESIGN.md)、每个包的`field-contract.json` |
| TI-06 | 搜索先返回短目标、状态、命中字段、原文片段和引用；`match`回查完整值及对应场景／事实，原show/source视图保留 | [阅读入口](test_intention/reader.py)、[检索与回查](test_intention/search_view.py) |
| TI-07 | 明确AND／OR，支持字段与路径限制；提供固定权重的字段BM25、TF-IDF和ID顺序；游标绑定查询、排序、原证据、索引与代码 | [离线比较程序](test_intention/p1_offline.py)、[独立复核](test_intention/p1_verify.py) |

新版本为`compact-intention-v3`。22个base共53,249条版本化测试记录，其中46,975条GENERATED、6,274条STATIC_FALLBACK；不同base中的同名测试分别计数。每个base的原证据数据库与v2逐字节一致，所以原测试身份、语义、场景、未知项和静态事实都未改写。没有重新解析AST或重新生成意图。

已有事实的非空覆盖：调用53,073、断言47,494、赋值45,203、条件4,964、mock 3,652、参数化16,730；限定名可拆出owner的记录45,734。没有单独保存的完整导入表、继承图、资源生命周期明确保留为缺口。表达式能搜到配置文本，不代表已经有完整配置键分析。

## 固定预算下的开发结果

比较方式在[设计](TEST_INTENTION_P1_DESIGN.md)中先确定：只从30PR的公开title/body按固定规则提取查询；每个PR一次OR查询、同样的6,000 UTF-8字节、最多25个分页单元。先封存全部排名、输出与哈希，再打开宿主机标签。

30PR中29个有正例，共361个已有测试目标。下面的召回是**首个检索页面完整展示的候选召回**，不是Agent最终选择，也不是三种SDD的新Detect指标。

| 组 | 匹配与展示方式 | 宏平均召回 | 微平均召回 | 命中目标 | 至少命中一个目标的PR比例 | 每页平均完整测试数 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| L | 旧身份＋语义JSON，完整卡片，ID排序 | 0.07% | 0.55% | 2/361 | 3.45% | 4.23 |
| T | 已有字段投影，完整卡片，ID排序 | 0.07% | 0.55% | 2/361 | 3.45% | 4.37 |
| S | 同T，短结果，ID排序 | 0.28% | 2.22% | 8/361 | 3.45% | 9.87 |
| R | 同S，字段BM25排序 | 37.64% | 6.65% | 24/361 | 41.38% | 10.20 |
| F | 同S，TF-IDF排序 | 33.08% | 5.82% | 21/361 | 41.38% | 10.23 |

宏平均先算每个正例PR的召回再平均；微平均直接算总命中／361。两者差距大，表示大量目标集中在仍然困难的PR中。无正例的PR8067单列：R展示10条候选，不能把它当作正确空输出；检索候选也不等于最终预测。

逐步比较给出的证据：

- **字段接入：**全部匹配集合的宏平均覆盖率由73.92%增至78.82%，目标覆盖从130增至151；单靠扩字段，ID顺序的首屏命中仍没有增加。T还排除了原JSON管理键的匹配，因此L→T同时包含正文匹配清理，不能称为完全纯粹的“只加字段”。
- **短结果：**T→S把平均完整可见测试数从4.37增至9.87，命中从2增至8；这次增量只发生于PR7968，不能推断普遍提高了正确选择能力。
- **排序：**S→R有12PR命中增加、1PR下降、17PR持平；R的候选精度为7.84%，MRR@预算为0.1205。F命中较少，但MRR为0.1498，首个目标位置指标更好；不据此宣称某个词法方法全面最优，也没有按标签重调权重。

下降与边界同样保留：PR7968有100个目标，S首屏命中8个，R为0个，F为1个；PR7808有175个目标，扩字段后的匹配集合仅覆盖10个，三种短结果首屏都未命中。排序无法找回根本没有进入匹配集合的测试。现有字段投影的微平均集合覆盖仅151/361＝41.83%，是当前查询与表示的明显限制，尚不能断定缺哪种新事实或关系。

短结果还需要后续阅读。对每个查询的第一条结果，无论其是否正确，R展开show平均需要1次额外调用、约1,312字节；这不包括Agent可能继续读取的源码、场景或其他候选。输出字节不折算为provider token。旧卡片全文单页结果与新短结果的对比只是阅读入口的比较，旧Agent通常会继续搜索，不能把L首屏0.07%当作旧SDD定位分数。

## 验收证据

最终交付为`p1-20261103-v2`。首版v1和其封存结果保留：评分后代码检查发现浮点累加遍历集合的顺序没有固定，v2只固定词项累加／词典序并增加跨hash seed检查，查询、字段权重、匹配条件和排序公式不变。该修复不是根据命中结果调参；[两版对照](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/v1-v2-comparison.json)确认公开查询逐字节相同、150组完整排名ID序列及全部指标值相同。v2修复时已看过v1评分，不能称为盲测；最终验收针对v2，开发集性质不变。

所有产物位于[本阶段目录](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2)。

- [22个base清单](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/bundles.json)：完整包约1.04 GB，包含原证据和新增搜索索引。存储增加换取已有字段可检索，默认展示仍受字节上限约束。
- [公开查询](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/queries.json)、[查询封存](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/query-seal.json)、[排名封存](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/rankings-seal.json)：30查询、150组完整排名及150份实际页面；标签不进入排名或表示。
- [逐PR指标](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/offline-metrics.json)、[独立复核](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/verification.json)：独立重组150份页面，按PR重算宏／微召回；实际运行冻结包的90条命令，页面内容和字节量均与封存结果一致。22个base再次通过宿主机清单校验。另增加3个不同Python hash seed下的原始分数及排序一致性检查。
- [回查及翻页检查](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/offline-checks.json)：核对909个首屏命中引用，82,089个全量分页单元按原顺序回收，无重复或遗漏。
- [相关检查](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/related-tests.log)：51项通过，其中11项为新增P1检查；覆盖回退记录、Unicode原文偏移、条件／动作／预期关联、变更后拒绝游标、长身份分片、独立运行及篡改检查。部分测试覆盖同一机制，不相加称为独立证据量。
- [原验收入口](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/acceptance.log)：95项、5/5组通过。
- [容器冒烟](/data2/wangzuohit/NLPU-experiments/test-intention/p1-20261103-v2/runtime-probe.json)：一个既有固定镜像在原AppArmor/seccomp与bubblewrap、只读挂载、网络none、UID1007下搜索及回查成功；未挂载模型凭据。其余90条命令是宿主机检查，不冒充90次容器验证。

## 如何使用与后续范围

新实验显式传入`compact_pilot.setup(..., representation_root=新目录/representations)`即可选择v3；默认仍使用原v2。`batch/stages.py`已识别v3并提供cursor/match说明。旧表示、旧执行根和历史预测不被自动切换。

例如，从仓库根目录使用挂载的新包：

```bash
python3 test-intentions/read.py search --query open_in_browser
python3 test-intentions/read.py search --query old_api --query mock --mode and
python3 test-intentions/read.py search --query keyword --cursor '上页的next_cursor'
python3 test-intentions/read.py match 'TEST_ID' --ref '/facts/calls/0/expression'
```

本次30PR是开发诊断集，不能用于泛化结论；同一PR没有因三种SDD而重复计为三个独立样本。68个本轮独立测试PR的标签未读取。当前结果支持继续检验“已有字段＋短结果＋排序”的机制，但真实完成率、最终召回和token收益仍需TI-12b中环境相同的D/E比较。TI-09／10是否启动，需要额外证据，本次未开展。
