# 结构与调用关系

```text
CGM Metric Library v2.0.0/
├── _SPEC/                 当前规范、计算合同、验收要求
├── 01_OriginalData/        数据占位；默认引用外部原始目录
├── 02_Logs/               本地开发记录
├── 03_Codes/
│   ├── pyproject.toml / uv.lock / .python-version
│   ├── .venv/             uv独立环境
│   ├── configs/           公共模板；*.local.yaml不入Git
│   ├── src/cgm_library/   contracts/io/qc/timeline/windows/
│   │                     sampling/events/metrics/studies/workflows
│   ├── tests/             合成边界与集成测试
│   └── tools/             请求准备、脱敏试运行、参考验证
├── 04_Manuals/             使用、字段、开发维护、发布说明
├── _RequestList/           请求占位；不复制患者请求
├── _Outputs/<run_id>/      配置、环境、QC、指标、日志、manifest
├── .github/workflows/     无患者数据的自动检查
├── README.md / CHANGELOG.md / CONTRIBUTING.md / SECURITY.md
└── start.py               根目录入口
```

调用方向：CLI→batch→patient→计算模块。输入适配负责格式；计算函数不自行寻找文件。事件不依赖MAGE插值，Sparse不依赖聚合序列；公共库不运行研究模型。

一次运行输出config.yaml、environment.yaml、qc_and_coverage/、metric_outputs/、logs/、manifest.json。已有run_id拒绝覆盖；请求附加列保留。交付沿用此结构，不另造旧示例ZIP目录。
