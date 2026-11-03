# CGM Metric Library v2.0.0

面向连续血糖监测数据的 Python 计算库。独立新工程创建于2026-11-04。
远程仓库：https://github.com/GuLifan/CGM-Metric-Library-v2.0

## 当前可用范围

支持文件读取/QC、五分钟时间轴、窗口与日夜覆盖、连续指标、低/高血糖事件、延长事件及内部连续低值段、条件低血糖分层、ADRR完整日敏感性、FBS、Sparse20→Sparse5、Full7以及逐患者继续的批次输出。
MAGE候选实现使用全窗口SD；正式MAGE字段保持NA，直到R参考差异得到核对和验收。新工程不是已完成临床验收的发布版。具体测试证据见[验收状态](04_Manuals/VALIDATION.md)。

## 最短安装与验证

```powershell
cd "D:\LifanDataAgent\CGM Metric Library v2.0.0\03_Codes"
uv sync --frozen --python 3.14.7
uv run pytest -q
uv run ruff check src tests tools
uv run cgm-library --help
uv run python tools/run_synthetic_pilot.py --run-id demo_001
```

日常无需安装到全局Python。依赖以uv.lock锁定；requirements.txt只用于兼容其他安装工具，由锁文件导出。

## 运行真实批次前

将configs/example.yaml复制成configs/site.local.yaml，填写原始无后缀目录、单位、采样频率和批次日期边界。此配置及真实输入不提交。请求前六列严格为：
住院号、出院日期、入院日期、设备文件名、胰岛素泵开始时间、胰岛素泵停止时间。
其后附加列保留；缺analysis_id时自动生成本批顺序ID。

```powershell
uv run cgm-library run --request "本地请求表.csv" --config configs/site.local.yaml --output-root ../_Outputs --run-id local_001 --accept-partial
```

根目录也可执行 `python start.py --help`。同一run_id禁止覆盖。每次输出配置、环境、QC、结果长表、逐患者状态及SHA-256清单；部分成功不会标成正式整批成功。

## 文档入口

- [_SPEC/CONSTITUTION.md](_SPEC/CONSTITUTION.md)：治理与生效规则。
- [_SPEC/METRIC_CONTRACT.md](_SPEC/METRIC_CONTRACT.md)：指标定义、输入输出。
- [_SPEC/DATA_FLOW.md](_SPEC/DATA_FLOW.md)：计算及异常流程。
- [_SPEC/ARCHITECTURE.md](_SPEC/ARCHITECTURE.md)：目录与模块职责。
- [最新会议裁定](_SPEC/DECISIONS_20261104.md)：M01—M07。
- [用户操作](04_Manuals/USER_GUIDE.md)、[字段说明](04_Manuals/DATA_DICTIONARY.md)、[开发维护](CONTRIBUTING.md)、[发布检查](04_Manuals/RELEASE.md)。

原始资料默认通过配置引用旧目录，无患者数据复制进本工程。旧算法的迁入不等于旧验收状态继承。未指定开源许可证，公开仓库不自动授予第三方再分发许可。
