# P0完成记录

日期：2026-11-03。范围为TI-11、TI-12a与TI-01～05；工程修复和本阶段离线验收完成。未启动新增模型实验，不能据此声称真实召回率已经提高。

## 交付与验证

| 任务 | 已交付内容 | 验收证据 |
| --- | --- | --- |
| TI-11 | 90行诊断表，区分终止原因、工具恢复、草稿／自检／终止时序、已知与缺失用量及归因置信程度 | [诊断表](/data2/wangzuohit/NLPU-experiments/test-intention/p0-20261103-v1/diagnosis-final/diagnosis.md)、[CSV](/data2/wangzuohit/NLPU-experiments/test-intention/p0-20261103-v1/diagnosis-final/diagnosis.csv)、[完整JSON](/data2/wangzuohit/NLPU-experiments/test-intention/p0-20261103-v1/diagnosis-final/diagnosis.json)、[失败复核](/data2/wangzuohit/NLPU-experiments/test-intention/p0-20261103-v1/diagnosis/manual-review.md) |
| TI-12a | 改动前固定机制分包、D/E/S比较组、预算、指标和失败规则，按预定排除规则落实30开发／68独立测试身份 | [设计与初始诊断](TEST_INTENTION_P0_DESIGN.md)、[身份划分](/data2/wangzuohit/NLPU-experiments/test-intention/p0-20261103-v1/data-split.json) |
| TI-01 | 通过既有允许的解释器启动SDD，Bash非交互与登录模式均有明确入口；保留grep/find/python替代，不安装rg/curl或放宽策略 | 22个base×3方法，共66/66容器＋bubblewrap检查通过 |
| TI-02 | 三种SDD的绝对规划目录、草稿位置、必要阶段和结束条件进入公共提示；新preflight检查规划写入和校验往返 | 同66项检查均通过；提示与路径回归通过 |
| TI-03 | 同一份stdlib实现、schema与版本用于Agent和宿主机；结构／身份分层；根数组返回明确错误；身份无效项仍沿用FP口径 | 根数组、嵌套限定名、歧义、fixture、越界路径、CLI／宿主机一致性及原封存评分验收通过 |
| TI-04 | 可修订过程草稿与待确认项独立保存、原子替换、180秒时间预留及原生budget提醒、最多3次不同草稿校验、未完成状态拒绝封存 | 真实子进程中断、替换中断、校验失败／上限、缓存、base变化和提醒不自动发布检查通过 |
| TI-05 | 身份计分规则与预测必要性分开，提供通用成对示例；明确AST相同与语义等价的不同边界 | 公开说明、AST标签回归及三种SDD提示检查通过 |

## 诊断改变了什么判断

64项封存、23项预算终止、2项余额不足、1项根类型处理异常，与旧终态一致。旧“88项出现错误”是文本信号；严格要求明确错误且命令非零退出后涉及64项，其中31项观察到同工具／对应入口后续成功的候选恢复证据。都不能当作致死任务数。

最终诊断补充了错误到候选恢复之间的命令数与输出字节窗口；窗口可能混入正常调查，因此不称为浪费量。初始修复前诊断仍保存在`diagnosis/`，最终表为`diagnosis-final/`。事件时钟缺失、首写仅有file_change可见事件等限制随每项记录保留。

“已有草稿”也不是成功潜力的保证：Spec Kit／PR7968的49个候选在事后标签上为11TP、38FP、89FN；PR7808的两份空草稿各175FN。因此收尾流程保留继续调查和修订，不因为有草稿就强制发布。25个会话缺完整provider用量，预算浪费和节省量保持未知。

工具修复的实际依据是容器内复现：补PATH和普通shebang脚本仍返回权限错误，使用已允许的Python／Node解释器启动后成功。没有调整AppArmor/seccomp或挂载模型凭据。`BASH_ENV`还通过显式子环境配置传入，避免被原`inherit=core`过滤；配置参数的shell引号和TOML类型已回归检查。

## 验收记录

- [容器检查汇总](/data2/wangzuohit/NLPU-experiments/test-intention/p0-20261103-v1/runtime-all/summary.json)：66/66通过，网络none、只读根、UID1007、原AppArmor/seccomp与bubblewrap；模型请求0，项目测试执行0。
- [新增P0回归](/data2/wangzuohit/NLPU-experiments/test-intention/p0-20261103-v1/p0-tests-final.log)：20项通过。
- [原离线验收入口](/data2/wangzuohit/NLPU-experiments/test-intention/p0-20261103-v1/acceptance-final.log)：95项、5/5组通过，禁止外部进程和网络的原验收机制保持通过。
- [相关表示／控制器／运行边界检查](/data2/wangzuohit/NLPU-experiments/test-intention/p0-20261103-v1/related-tests-final.log)：32项通过。另有23项batch相关检查通过，部分与上述验收重叠，不相加称为独立测试总数。

第一次容器检查的脚本入口失败、修复前的验收失败记录均保留，最终通过记录另存，没有覆盖历史定位结果。

## 实现入口与边界

公开工具位于[public_detect](../sdd-bench/scrapy-sdd/batch/public_detect/README.md)，只依赖stdlib和公开base。每次新Detect运行单独复制只读运行快照，保存全部文件哈希；宿主机确认校验器与Agent快照一致。未来独立执行根会复制该目录并固定其哈希。preflight保存原始工具检查证据，避免只留下无法复核的哈希。

新草稿协议与提示通过`batch/stages.py`接入。Update不启用本次Detect公共环境和提示。原100,000 rollout限额、2700秒期限、三种SDD必要阶段、历史预测与评分保持原有口径。

收尾提示和辅助工具不能强制Agent所有shell操作都遵循预算流程；`validate`也可被独立调用。有限校验约束针对推荐的`finalize`流程，真实节省仍待TI-12b验证。静态身份合法不代表方法需要更新；调查完整性不能通过格式校验得出。

后续P1和P2仍未开始。独立测试的68PR曾用于其他历史方法，只与本轮P0调优隔离；不能称为项目从未见过的数据。P0当前没有新的定位分数，没有充值、重试失败模型目标或运行方案二。
