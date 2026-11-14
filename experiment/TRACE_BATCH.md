# 全 base 动态覆盖批次

`trace_batch.py` 根据既有实验 `per-pr.json` 的 `pr_id` 和 `base_sha` 白名单字段
去重 base。采集阶段不读取修改标签，不按修改测试选择执行范围。

```bash
python3 -m experiment.trace_batch prepare \
  --retrieval-run /path/to/existing-run \
  --benchmark /path/to/benchmark \
  --output /path/to/new-batch \
  --scratch-root /path/to/disposable-worker-scratch \
  --image-template 'caller-baseline:{base}' \
  --production-root src/library --test-path tests \
  --base-concurrency 4 --workers 16

python3 /path/to/new-batch/code/batch_driver.py preflight \
  --plan /path/to/new-batch/plan.json
python3 /path/to/new-batch/code/batch_driver.py run \
  --plan /path/to/new-batch/plan.json
```

每个 base 使用对应的现有冻结源码和镜像。准备时校验全部 checkout 文件哈希、
可执行位、镜像 base 标签，并冻结采集程序、配置和去重范围。`--image-map`
可提供 caller 准备的 `base -> image digest/tag` JSON；选择完成后固定为镜像 digest。
环境需要修复时，在采集器之外生成新镜像，保留依赖与构建记录，不修改 base 源码。

先为全部新 base 完成测试发现 preflight，全部通过后才允许启动完整采集。
`--reuse-bundle` 复用已验证、全部发现实例均有终态记录的旧包，其原有采集版本和
运行环境不会被改写。`--external-terminal-map` 可等待另一个已在运行的同 base
任务封存，避免重复执行；仍会重新验证其包。

每个测试 120 秒、发现阶段 600 秒；没有总调度预算截断，未记录的实例会继续
执行。每个实例用独立进程和独立源码副本，runtime 网络为 none。结果持续写入
`runs/` 的耐久记录中，scratch 只存放可丢弃工作目录。测试不自动重试。

批次入口 `index.html` 和 `status.json` 显示所有 base 的 PENDING、RUNNING、
SEALED、REUSED_VERIFIED、SEALED_WITH_GAPS、FAILED 状态。封存表示结果已保存，
不表示每个测试都通过。失败或未知覆盖保持显式状态。每个成功 base 的
`views/<base>.html` 可检索源码测试并打开完整覆盖/图 JSON；HTML/SVG 调用图可用
对应包的 `query.py export` 生成。`dynamic-trace-artifacts.json` 保存可供三套
SDD 共用的 base/manifest 路径与哈希映射，不包含更新标签。

协调器使用独占锁；重启同一个冻结批次会跳过已有终态 base 和已有终态实例，
不会自动重跑失败项。不得在运行中修改 `code/` 或 `configs/`；改变环境、策略
或程序时建立新批次并保留旧记录。

采集封存后，宿主侧按 [共同修改分析说明](TRACE_COCHANGE.md) 连接已有方法级
修改标签。该步骤独立于采集和 SDD 输入，覆盖包不包含宿主分析结果。
