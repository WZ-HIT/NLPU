# BGE 方法级测试候选检索

沿用已确认的 98 个 Scrapy PR、原始 title/body、base 中的测试身份及源码文档、Top-50/100/200 和评价规则。检索方法为 `BAAI/bge-base-en-v1.5` 的向量余弦相似度。

## 模型与编码

- 固定模型 revision：`a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`。
- 官方 `onnx/model.onnx` 的 SHA-256：`9bc579acdba21c253c62a9bf866891355a63ffa3442b52c8a37d75b2ccb91848`。启动时校验该值。
- 原始文档仍是路径、限定名与完整源码，按原有 `document_sha256` 校验字节一致。BGE 使用原生 WordPiece，不预先调用词法基线的拆词函数。
- 查询添加官方检索指令；文档不加。CLS pooling、768 维、L2 归一化、余弦排序。
- 最长 512 tokens，右截断并保留 CLS/SEP，不分块、不摘要。截断统计保存在报告与逐项元数据中。
- CPU ONNX FP32，16 线程、batch size 16；未做量化或微调。

模型依据：[官方模型卡](https://huggingface.co/BAAI/bge-base-en-v1.5)。

## 本地运行

依赖固定在 [bge-runtime-requirements.txt](bge-runtime-requirements.txt)。本次使用数据盘上的独立环境及模型，避免占用接近满额的系统盘。

```bash
OPENBLAS_NUM_THREADS=1 /data2/wangzuohit/nlpu-bge/venv/bin/python \
  -m experiment.bge_localization \
  --output-dir /data2/wangzuohit/nlpu-bge/results/<new-run-id>
```

可通过 `--model-dir`、`--embedding-cache`、`--threads`、`--batch-size` 和各输入参数改变路径或运行资源。模型目录包含 `model.onnx`（官方 ONNX 文件）、`tokenizer.json`、`config.json`、`tokenizer_config.json`。模型 ID、权重、池化与长度策略固定。

全部检索排名、文档向量与查询向量先写入并校验，之后才构造宿主机评价标签。独立校验重新计算保存向量的余弦分数、逐 PR 指标和汇总指标。比较时核对三轮的原始查询、base、候选文档字节和参考标签一致。

向量缓存按模型文件、编码实现、配置和有效 token ID 绑定。冷缓存文档准备成本与后续暖缓存实验时长分别记录。

## 本次产物

项目内入口为 `output/bge-localization/scrapy-98pr-20261027-v1`，指向数据盘上的完整产物。核心文件：

- `comparison.md` / `comparison.json`：与 BM25、TF-IDF 的同范围结果。
- `report.md`：协议、截断统计和逐 PR 分数。
- `candidates-top200.csv`：可筛选的测试候选及 Top-50/100/200 标记。
- `predictions/`、`vectors/`、`queries/`：封存排名与实际使用的向量。
- `verification.json`：独立重算结果。
- `manifest.json`、`source-snapshot/`、`requirements.lock.txt`：输入、模型、依赖和实现的追溯资料。
- `cache-precompute.json`：文档向量预计算成本，不与暖缓存实验时间混用。

实验运行需本地模型依赖；无需模型依赖的旧基线仍使用原来的 Python 环境。
