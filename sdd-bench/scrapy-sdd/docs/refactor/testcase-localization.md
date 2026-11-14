# 文件与 testcase 双粒度定位

协议：`testcase-v1`。封存格式：`detection-v2`。新增指标：`detect-metrics-v3`。
历史 `detection-v1` 和 `detect-metrics-v2` 继续读取，不修改已有配置、ledger 或 seal。

## 一条命令离线验收

在 NLPU 根目录执行：

```bash
python3 sdd-bench/scrapy-sdd/bin/check-testcase
```

在 benchmark 目录也可执行 `python3 bin/check-testcase`。脚本定位自身所在目录，
不需要 CONFIG、ROUND 或 PYTHONPATH。四组检查覆盖身份与标签、评分、假 Agent 流程、
历史兼容与运行边界。失败显示具体检查并返回非零退出码。

脚本使用临时样例，阻止外部进程和网络连接，不调用模型、不启动 Docker、不修改历史实验。
其中假 Agent 走统一 run 入口、真实阶段封存、追加式 ledger、全批 Detect 屏障、宿主机评分及页面读取；
prepare 使用假的 scaffold/audit/preflight，检查新索引的冻结、复用和哈希冲突。
这验证程序契约，不证明真实模型的定位效果。依赖与原 benchmark 相同，包括 `jsonschema`。

## 定位对象与输入

- 最终定位需要修改内容的**已有测试函数／方法**；相关但无需修改的测试不是最终正目标。
- 一个源码方法算一个 testcase，参数化执行实例合并。多条断言仍算一个。
- 身份为 `path::ClassName.test_method` 或 `path::test_function`，绑定任务与 base SHA。
- 不使用方法裸名模糊匹配，不将文件预测扩张为全部方法预测。
- Agent 输入仍为原任务描述与允许的 base 仓库，不提供当前实现 diff、gold 或新增检索信息。
- 从 base 静态提取的测试清单只供宿主机校验，不作为新 Agent 挂载或 prompt 附件。

`batch/testcase_identity.py` 不访问 gold、不导入目标仓库、不执行测试。
源码清单覆盖 test/、tests/ 下按 test 前缀命名的普通和异步定义，排除可识别的 fixture 和嵌套 helper。
这是源码定义协议，不声称复现 pytest 全部动态收集行为；继承方法的执行别名、动态生成、
自定义收集和 fixture 装饰器别名等需要另行审核，不自动猜测映射。

## 配置与冻结

新的独立配置示例为 `batch/experiments/scrapy-3pr-testcase-v1.json`，选择原始 3 PR：8064、8067、8073。
所有三种方法共用以下配置：

```json
"evaluation": {
  "kind": "detect-host",
  "localization_protocol": "testcase-v1"
}
```

不设置 `localization_protocol` 的旧配置保留原文件级运行要求。协议字段属于配置哈希，
会产生新的 round 身份，即使 PR 和原始五元目标键相同，也有独立任务树和 ledger。
不要编辑旧配置或复用旧轮次作为新协议的实验。

prepare 在轮次根目录的 `testcase-indexes/<base>.json` 冻结清单，并在 prepared-round 的
`testcase_indexes` 与 evidence 中记录路径和 SHA-256。该目录位于任务输入树之外。
已有清单先比对再复用；冲突立即停止。加载 manifest 重新核对引用、baseline 文件哈希和清单内容。

## 输出

```json
{
  "candidates": [
    {
      "path": "tests/test_example.py",
      "symbols": ["TestExample.test_timeout"],
      "reason": "任务改变了该测试依赖的预期行为"
    }
  ]
}
```

`candidates: []` 是明确的空预测。新协议中每个报告文件必须附非空 symbols；
只报文件属于格式失败。不存在、含糊或错误的方法身份照实封存，由宿主机计为无效预测和 FP，
不自动修正。重复身份去重，另记重复数。新 seal 明确记录 `localization_protocol`。
三种方法的运行提示遵守相同要求，不同时引入其他定位增强。

## 宿主机参考标签

`batch/testcase_labels.py` 读取批准计划中按哈希固定的原始记录，将每条
`(file, qualified_name, old_test, gold_test)` 与已校验 base 配对。不会用分离的文件列表和方法列表拼接答案。

主标签取 base 已有、旧内容可核实、内容发生变化的 modified 测试。
新增、删除、显式重命名、helper/fixture 和 AST 相同的纯格式／注释变化分别记录，不进入主标签。
原始记录以 added/deleted 表示的潜在重命名不会自动配对或宣称已识别。
无法解析或无法对齐的记录使整个任务标记 `LABELS_INCOMPLETE`，不以部分标签计算高分。

AST 比较不能识别所有机械变化，签名或文档字符串变化也可能进入代理标签。
开发者改动不是完备真值，分歧抽样人工复核并单独报告，不看完预测再随意调整同轮标签。
原始矿工可能不枚举所有 helper/fixture，排除计数仅针对原始记录中的项目，不代表完整辅助代码审计。
方法片段用缩进包装解析，不 dedent 多行字符串，防止破坏字符串语义后误报旧源码不一致。

## 三套指标与状态

| 视图 | 预测与参考集合 | 兼容性 |
| --- | --- | --- |
| `legacy_file` | 原文件预测与原 gold 文件 | 原 v2 算法及分数保持不变 |
| `scoped_file` | 明确报告的文件与主 testcase 标签投影的文件 | 新增同范围文件级指标 |
| `testcase` | 完整测试方法身份与主 testcase 标签 | 新主指标，F1 为主要汇总值 |

每套新增指标报 P/R/F1、TP/FP/FN、预测数和 gold 数；每种方法报按 PR 宏平均、总体微平均，
另报只对成功运行计算的条件分数。合法空预测 P/R/F1 均为 0（gold 非空）。
无效方法预测作为 FP 进入 testcase 分母，不因过滤无效值而提高精度。

| 状态 | 主指标处理 |
| --- | --- |
| `OK` | 新协议正常计分 |
| `FAILED_ZERO` | FAILED/BLOCKED 且 gold 非空，按空预测计零；进入主汇总 |
| `HISTORICAL_RESCORED` | 旧 seal 有明确方法身份，可以严格追溯评分；与新协议分开展示 |
| `HISTORICAL_UNSCORABLE` | 旧输出为空或有文件缺少方法，不把缺失身份当空预测 |
| `NO_POSITIVE_GOLD` | 不进入正目标任务 F1 平均，另报方法预测的误报数 |
| `LABELS_INCOMPLETE` | 标签或 base 解析不完整，明确列出缺口 |
| `EVIDENCE_INVALID` | seal、身份、hash 或 bundle 核验失败，不给可信分数 |
| `PENDING` | 尚未有终态，不假定运行失败 |

失败数按原运行状态统计，即使标签不完整也不隐藏失败。不可评分数、实际计分数、状态分布、
无效／重复预测数及无正目标误报数均显式报告。标签和证据缺口使报告为 PARTIAL。
与旧指标的差异包括 gold 范围、方法身份校验、无效预测惩罚以及失败计零，应按版本解释。

## 手动开展新轮次

以下是交付后的操作方式，本次没有执行真实 prepare 或模型运行。
prepare 会使用现有 Docker/preflight 机制；仅离线验收不需要 Docker。

```bash
cd ~/NLPU/sdd-bench/scrapy-sdd
CONFIG=batch/experiments/scrapy-3pr-testcase-v1.json
ROUND=testcase-001
python3 bin/sdd-experiment prepare "$CONFIG" --round "$ROUND"
# 确定要调用模型后，才执行下一条：
python3 bin/sdd-experiment run "$CONFIG" --round "$ROUND" --stage detect --execute
python3 bin/sdd-experiment evaluate "$CONFIG" --round "$ROUND" --kind testcase
sdd-results
```

`evaluate --kind testcase` 允许部分失败批次，读取并核验已有证据，不启动模型、Docker 或测试。
PARTIAL 会保存报告并返回非零退出码。运行屏障本身不变；Update 仍要求全批 Detect 完成。
新协议下 `evaluate --kind detect` 在原有完整 Detect 校验后生成旧 v2 与新 v3 报告。

历史轮次或旧批次可以在宿主机追溯评分：

```bash
python3 bin/sdd-detect-metrics check --batch <实际的批次或round-ID> --testcase
```

可加 `--dry-run` 只计算不写文件。旧命令不加 `--testcase` 时保持既有含义。

v3 另存在 `Log/reports/testcase-metrics/<batch-ID>.json`，目录 0700、文件 0600。
它引用原 target_key/target_id、ledger 事件、seal、原始输入和 baseline 哈希。
不覆盖 `Log/reports/detect-metrics/` 的历史 v2 报告。
results 页面读取这个报告，显示计数和分数；不向页面导出 gold 方法身份或源码。
运行态 result view 仍不含 gold 或评分标签。

## 本次验证

- 一键离线验收：4 组、78 项检查通过（含 token 记录与页面兼容）；包含新的准备/复用/冲突及真实封存流程。
- 额外已有兼容测试：69 项通过，含真实历史 3 PR 文件级分数回归。
- 历史三轮只读审计见 [testcase-history-audit.json](testcase-history-audit.json)。
  98 个 PR 的标签均完整对齐；590 个历史受保护文件哈希未变。
- 不将旧输出中的 class 名、通配符或非规范方法名猜测转换为正确 testcase。
  严格追溯评分中的高无效预测数，不等同于在新协议下真实重跑的模型能力。
- 未运行真实模型、Docker、目标测试或全量 SDD 测试集；离线验收不承诺实际模型效果。

Token 记录、缺失／过期评分提示及页面操作见 [结果页面与 token 用量](token-usage.md)。
