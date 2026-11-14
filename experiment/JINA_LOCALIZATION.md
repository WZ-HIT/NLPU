# Jina-code 方法级测试候选检索

本实验沿用同一批 98 个 Scrapy PR、原始 title/body、base 中的源码测试定义、完整文档字节、宿主机标签、Top-50/100/200 和既有指标公式。

## 固定模型配置

- 模型：`jinaai/jina-embeddings-v2-base-code`。
- Revision：`516f4baf13dec4ddddda8631e019b5737c8bc250`。
- 官方 `onnx/model.onnx` SHA-256：`63363fc178428b74620c6f3780cbc7191883fa5c7f84c0945c45eb5c4256733b`。启动时强制校验。
- 原生、区分大小写的 byte-level BPE，保留源码原文，不调用词法基线的预分词。
- 查询与测试文档均不添加指令或任务前缀。
- 按 attention mask 进行 mean pooling，包含真实特殊 token、排除 padding，然后 L2 归一化并计算余弦相似度。
- 768 维，最长 8,192 tokens；必要时右截断、保留 BOS/EOS，不分块或生成摘要。
- 官方 FP32 ONNX、CPU 16 线程，最大 batch size 16。长输入按长度缩小批量，避免因 padding 放大内存需求；不量化、不微调。

配置依据：[官方模型卡](https://huggingface.co/jinaai/jina-embeddings-v2-base-code)。实机检查复现了官方示例的相似度，并验证了超过 512 tokens 的输入。

## 本地运行与追溯

依赖见 [jina-runtime-requirements.txt](jina-runtime-requirements.txt)。复用既有只读模型运行环境，模型、向量缓存与产物使用独立数据盘目录。

```bash
OPENBLAS_NUM_THREADS=1 /data2/wangzuohit/nlpu-bge/venv/bin/python \
  -m experiment.jina_localization \
  --output-dir /data2/wangzuohit/nlpu-jina-code/results/<new-run-id>
```

可通过 `--model-dir`、`--embedding-cache`、`--threads`、`--batch-size` 和输入参数改变路径或运行资源。模型目录包含 `model.onnx`、`tokenizer.json`、`config.json`、`tokenizer_config.json`。模型版本、池化与长度策略固定。

向量缓存按模型文件、编码实现、配置和有效 token ID 绑定。所有排名以及文档/查询向量封存并校验后，才构造宿主机评价标签。独立校验重新计算保存向量的余弦分数、逐 PR 指标和汇总指标。

对照 BM25、TF-IDF 和 BGE 时，逐项核对原始查询、base、候选源码文档字节、参考标签及评分范围相同；各模型自带的分词、池化、前缀与长度策略在报告中明确列出。

项目内入口为 `output/jina-localization/scrapy-98pr-20261027-v1`，链接到数据盘完整产物：

- `comparison.md/json`：四种方法的同范围结果。
- `report.md`：协议、截断数量和逐 PR 指标。
- `candidates-top200.csv`：候选测试及 Top-50/100/200 标记。
- `predictions/`、`vectors/`、`queries/`：封存排名与实际使用的向量。
- `verification.json`：余弦和指标的独立重算。
- `manifest.json`、`source-snapshot/`、`requirements.lock.txt`：输入、模型、实现和依赖追溯。
- `cache-precompute.json`：冷缓存文档预计算成本，与本轮暖缓存运行时间分别记录。

已有三种方法的实现和封存产物保持各自版本，未用于调节本轮模型配置。
