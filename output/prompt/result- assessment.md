# 1 scrapy
354 条 raw PR
├── 53：CI 不成功
├── 105：CI 成功，但没有修改 pytest 文件
└── 196：CI 成功且修改了 pytest 文件
    ├── 36：找到可靠 focal method
    ├── 62：没有可靠 focal，但有 modified old test
    ├── 91：只有 added/deleted test，没有 old test 可更新
    ├── 6：AST 没提取出 test
    └── 1：checkout 失败
98 / 196 = 50%， 其中剩余失败的测试均是只有新增或删除