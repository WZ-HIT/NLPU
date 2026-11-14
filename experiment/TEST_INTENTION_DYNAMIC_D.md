# D 组：C 的 TI＋完整动态调用图与两层共享

用户于 2026-11-13 逐项确认并批准构建。D 保留 C 的语义、静态事实、身份与搜索排序；只向 SDD 提供 complete 方法的独立动态事实。首批为原 A/B/C 相同 30 PR、22 base。模型实验尚未启动。

## 实现和使用

- `test_intention/dynamic_bundle.py`：通用离线导出，将冻结 C 与同 base 的轨迹连接，保留原 C 文件及索引；不读标签、不重新采集、不调用模型。
- `dynamic_view.py`：stdlib 运行时视图，逐 valid 实例 BFS、覆盖集合、调用图、两层共享及频率排序。
- `dynamic_reader.py`：加法式读取器，旧命令转交原 C；show 增加动态摘要，新增 coverage/trace/shared。
- `dynamic_offline.py`：独立复算层级和路径、检查原 C 与搜索保持一致、核验共享邻居、三 SDD 挂载和提示入口。

```bash
python3 -m experiment.test_intention.dynamic_bundle \
  --scope /data2/wangzuohit/NLPU-experiments/test-intention/stage-c-bc-20261110-v1/plan.json \
  --c-materials /data2/wangzuohit/NLPU-experiments/test-intention/stage-c-20261109-v1/materials/C \
  --trace-artifacts /data2/wangzuohit/NLPU-experiments/test-trace/20261112-all98-v2/dynamic-trace-artifacts.json \
  --output NEW_PUBLICATION

python3 -m experiment.test_intention.dynamic_offline \
  --publication NEW_PUBLICATION \
  --c-materials /data2/wangzuohit/NLPU-experiments/test-intention/stage-c-20261109-v1/materials/C \
  --trace-artifacts /data2/wangzuohit/NLPU-experiments/test-trace/20261112-all98-v2/dynamic-trace-artifacts.json \
  --benchmark /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd
```

在导出的 base 材料内，使用 `python3 read.py show/coverage/trace/shared TEST_ID`；`trace --depth 0` 分页读取完整图，`trace --instance EXECUTION_ID` 读取一个实际执行图，`shared TEST_ID --with OTHER_TEST_ID` 展开一对测试的全部共享函数及双方路径。默认每页 8 条／6,000 字节，最大 25 条／12,000 字节；超长记录使用显式片段并可继续读取。

shared 的双方必须 complete，同一生产函数在双方各自实例中的根距离都不超过 2。支持实例路径是证明，不能在方法聚合图拼接跨实例边。频率按同 base 完整 TI 测试方法的全生产覆盖计数。邻居按最低共享函数频率、共享数量降序、ID 排序，没有永久截断。原 neighbors 是静态关系，含义不变。

partial/unavailable/not_discovered 保留原 TI 与动态状态；动态覆盖和图不进入 D，包括底层数据库和公开文件。D 不同时挂载原始 test-traces，避免旁路暴露部分轨迹。卡片不会把运行事实写入模型生成语义，也不归属到特定场景。

## 本次产物

`/data2/wangzuohit/NLPU-experiments/test-intention/dynamic-d-20261113-v1/`。

材料位于 `materials/D/BASE/`；`scope.json/materials.json` 绑定范围和逐 base 哈希；`offline-acceptance.json/completion.json/REPORT.md` 表示离线验证；`offline/BASE-examples.json` 是真实读取示例。它不是已完成的 C/D 定位实验，也没有新的召回或成本结论。

同环境 C/D 对照另行确定启动规模和预算；未来应使用相同 PR/base/原 TI/实际模型配置/预算，并保留失败和未知。旧 C 仅作历史参考。正式批准决策见独立 context 的 `decisions/dynamic-ti-d-v1.md`。
