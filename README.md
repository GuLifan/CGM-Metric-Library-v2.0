# CGM Metric Library v2.0.0

连续血糖监测（CGM）研究计算库 · Research software for continuous glucose monitoring  
**计算库版本 / Package version** `2.0.0`　 **本次订正标识 / Revision label** `261112` (2026-11-12)

## 项目沿革 / Project history

| 阶段 / Stage | 中文 | English |
|---|---|---|
| 2026-07 至 09 · DRQ | 早期工程以请求清单驱动多个独立脚本。分组结果按全记录、住院期、出院前等窗口导出，专项脚本另算出院前 72 小时指标和前 24 小时昼夜分位数。旧表的 CV 和范围占比常以 0–1 比例保存。 | The DRQ scripts processed request lists and produced separate files by window. A dedicated pipeline calculated pre-discharge features. Legacy CV and range fractions often used a 0–1 scale. |
| 2026-10 · v2.0 | 将窗口指标、事件、覆盖率、稀疏取点与患者摘要拆成机器可读表。10 月 1 日的宽表衍生出五张中文分类 Excel；10 月 2 日另有修订计算归档。复核时需要记录具体归档。 | v2.0 separated window metrics, events, coverage, sparse samples and patient summaries. The five-sheet classified workbook came from the October 1 wide table. The October 2 corrected calculations are a separate snapshot. |
| 2026-11-04 · v2.0.0 | 建立独立的 Python/uv 工程，将输入、时间轴、事件、窗口和输出规则写入版本化规范。固定合成测试、逐患者错误记录和资产哈希。正式 MAGE 等待参考验收。 | The independent Python/uv project introduced versioned contracts, synthetic tests, per-patient outcomes and file hashes. Formal MAGE remains pending reference validation. |
| 2026-11-09 · 计算订正 | 同时刻重复值先按有效候选处理。五分钟槽按组首归窗，有效支持时长裁至窗末。标称一分钟来源的过满槽记录为患者级错误。 | Duplicate timestamps are resolved using valid readings. Slot starts determine window membership and support is clipped at the window end. Overfull slots in nominal one-minute data produce patient-level errors. |
| 261109 · 表格订正 | 计算使用原精度，导出小数按十进制四舍五入至四位。Excel 表头、标签和数值统一为 Times New Roman。首个有效读数已达或晚于出院的请求记 ERROR04，继续下一例。 | Calculations retain working precision. Decimal results use four-place half-up rounding at export. Excel headers, labels and values use Times New Roman. A first valid reading at or after discharge produces a patient-level ERROR04. |
| 261110 · DRQ扩展 | 新增13张窗口CSV、FBS序列、14张CGM日工作表和Mode7泵期间；DRQ入口允许出院后才开始记录。 | Added 13 window CSVs, FBS, 14 CGM-day sheets and Mode7. The DRQ entry accepts post-discharge-only recordings. |
| 261111 · 交付精简 | 删除交付analysis_id，统一Mode删列，保留低血糖次数。NewMetric归档仍来自261109，因此与DRQ存在两例资格差异。 | Removed delivery analysis IDs and redundant Mode columns. Archived NewMetric remained from 261109, causing two eligibility differences. |
| 261112 · 统一与随访 | 撤销旧入口对出院后才开始CGM的整例拒绝，Sparse目标按原协议保留缺失原因。Mode、daily、ATTD与NewMetric同批生成，新增出院后逐日和可读低血糖事件明细。 | Removed the old global rejection while retaining sparse-target eligibility reasons. Mode, daily, ATTD and NewMetric now share one run, with discharge-anchored daily results and readable hypoglycemia events. |

## 部署 / Deployment

当前推荐使用`deliver`命令。它保留已批准的精简列，交付表不含analysis_id，出院后Dn严格遵从出院时刻加24小时的边界，末日分母仍为完整24小时。时间显示日期和时分秒，不添加时区后缀。CGM从出院后开始是允许情形，各窗口独立检查覆盖率。261112规则取代261109的整例ERROR04限制。

Use `deliver` for the current revision. It retains the approved slim schema, omits delivery
analysis IDs and creates exact 24-hour follow-up days anchored at discharge. The final day
keeps a 24-hour denominator. Delivered timestamps show local dates and clock times without
suffixes. A recording may start after discharge; eligibility is checked per window. This
supersedes the 261109 global ERROR04 rule.

完成下述安装后，从03_Codes执行当前交付命令，详细规则见[出院后逐日交付指南](04_Manuals/FOLLOWUP_DELIVERY.md)。

After installation below, run the current delivery command from 03_Codes. The follow-up guide
documents every table, window, event and missing-value rule.

```sh
uv run --frozen cgm-library deliver --request ../_RequestList/request.csv --config configs/site.local.yaml --output-root ../_Outputs --run-id CML2204_261112 --prefix DRQ261112_CML2.0_2204 --workers 4 --accept-partial
uv run --frozen python tools/validate_delivery.py ../_Outputs/CML2204_261112
uv run --frozen python tools/package_delivery.py ../_Outputs/CML2204_261112 ../_Outputs/DRQ261112_CML2.0_2204.zip
```

261110 增加经批准的 DRQ 15 表输出、Mode7 胰岛素泵期间窗口，以及完整结果包的可还原单 CSV。操作详见下方 DRQ 交付指南。

Revision 261110 adds the approved 15-file DRQ suite, Mode7 insulin pump treatment window, and a reversible single-CSV result archive. The linked DRQ guide documents these commands and definitions.

在可读取原始设备文件的工作站或服务器安装 Git 和 uv。本项目要求 Python 3.14.7 至 3.14.x。使用仓库的锁文件建立独立环境。常规批次仅需 Python，R 仅用于独立的 MAGE 参考复核。

Install Git and uv on the workstation or server that holds the original device files. The supported Python range is 3.14.7 to the end of 3.14.x. The lock file pins dependencies. Routine batches use Python. R is needed only to reproduce the separate MAGE reference comparison.

```sh
git clone https://github.com/GuLifan/CGM-Metric-Library-v2.0.git
cd CGM-Metric-Library-v2.0/03_Codes
uv python install 3.14.7
uv sync --frozen --python 3.14.7
uv run --frozen cgm-library --version
uv run --frozen pytest -q
uv run --frozen ruff check src tests tools
uv run --frozen ruff format --check src tests tools
uv run --frozen python tools/run_synthetic_pilot.py --run-id demo_261109
```

上述命令适用于 PowerShell 及常见 POSIX shell。后续命令均从 `03_Codes` 执行。合成示范写入 `../_Outputs/demo_261109`。重复运行请选择新批次名。Excel 客户端安装 Times New Roman 可按指定字体显示，缺失字形的显示由客户端字体回退决定。

The commands work in PowerShell and common POSIX shells. Run the following commands from `03_Codes`. The synthetic pilot writes to `../_Outputs/demo_261109`. Choose a fresh run ID for every execution. Install Times New Roman on the viewing system for the intended appearance. The viewer controls fallback for missing glyphs.

### 配置与输入 / Configure sources and requests

1. 将 `configs/example.yaml` 复制为 `configs/site.local.yaml`。每项来源填写原始目录、标称采样间隔（1 或 5 分钟）和单位（`mmol/L` 或 `mg/dL`）。目录相对配置文件解析。  
   Copy `configs/example.yaml` to `configs/site.local.yaml`. For each original source, set its directory, nominal interval (1 or 5 minutes) and unit. Relative paths resolve against the configuration file.
2. 每例的出院自然日必须落入唯一来源区间。起日包含、止日排除；时间按亚洲上海时区解释。设备文件名须能唯一匹配原始 CSV、XLSX 或 XLS。  
   Each discharge date must select exactly one source. Date ranges include their start and exclude their end. Times are interpreted in Asia/Shanghai. The device filename must identify one original CSV, XLSX or XLS file.
3. 准备本地 CSV 请求清单。前六列按下行顺序填写；住院号保留前导零。可追加唯一的 `analysis_id` 及研究字段。缺少 `analysis_id` 时按请求顺序分配。  
   Prepare a local request CSV with the six literal headers below in this order. Preserve leading zeros in hospital IDs. A unique `analysis_id` and additional study fields may follow. If omitted, analysis IDs are assigned in request order.

```csv
住院号,出院日期,入院日期,设备文件名,胰岛素泵开始时间,胰岛素泵停止时间
```

### 运行与核验 / Run and verify

```sh
uv run --frozen cgm-library run --request ../_RequestList/request.csv --config configs/site.local.yaml --output-root ../_Outputs --run-id CML2204_261109 --accept-partial
uv run --frozen python tools/validate_outputs.py ../_Outputs/CML2204_261109
```

`--accept-partial` 表示接受尚有 MAGE 参考验收项的研究输出。退出码 0 也可能包含患者级失败，请查终态和逐例日志。CLI 在全部患者失败时返回 1；配置、参数或批次名错误需查终端提示。更正输入后使用新 run ID 复算。库可在本地运行，无需数据库服务。

`--accept-partial` acknowledges the outstanding MAGE reference gate. Exit code 0 can include patient-level failures. Inspect the terminal state and per-patient log. The CLI returns 1 when every patient fails. Configuration, argument and run-ID errors are reported in the terminal. Use a new run ID after correcting inputs. The batch runs locally without a database service.

| 输出 / Output | 用途 / Use |
|---|---|
| `<run_id>_patient_summary.xlsx` | 查患者状态、未计算病例、窗口指标、Full7 和 Sparse5。Excel 使用数值单元格，保留文本标识。 / Review outcomes, failed cases, window metrics and ATTD features. Values are numeric cells and identifiers retain their text type. |
| `metric_outputs/` | 窗口、昼夜、事件与 ATTD 长表。百分数字段以 0–100 表示。 / Window, day/night, event and ATTD tables. Percentage fields use a 0–100 scale. |
| `qc_and_coverage/`、`logs/patient_status.csv` | 追查覆盖率、原始异常、五分钟时间轴和逐例失败原因。 / Trace coverage, raw anomalies, five-minute timelines and patient-level failures. |
| `manifest.json`、`manifest.sha256`、`run_state.json` | 核对批次状态、输入/输出与源码摘要、资产完整性。 / Verify terminal state, input/output and source hashes, and artifact integrity. |

CSV 采用 UTF-8 BOM，保存数值和文本。字体由 Excel 工作簿记录。整数计数保留整数，缺失留空，零保留为零。精确阈值、MAGE 候选计算及事件判定均在导出前执行。需要高于四位精度的二次分析时，请从原始输入和同一版本的计算库取值。

CSV uses UTF-8 with BOM and carries values and text. Font metadata lives in the Excel workbook. Integer counts remain integers, missing cells remain blank, and observed zeros are retained. Threshold decisions, candidate MAGE and event detection precede export rounding. For analyses requiring more precision, use the original inputs and the same version of the calculation library.

## 规范、验收及维护 / Specifications, validation and maintenance

DRQ 全套15表、Mode7泵期间和完整结果包单CSV的运行、字段及还原方法见 [DRQ交付指南](04_Manuals/DRQ_DELIVERY.md)。

See the DRQ delivery guide for the 15-file suite, Mode7 pump period, and reversible single-CSV export of a complete result archive.

- 指标定义与变更裁定 / Metric contract and dated decisions: [Metric contract](_SPEC/METRIC_CONTRACT.md) · [2026-11-04](_SPEC/DECISIONS_20261104.md) · [2026-11-09](_SPEC/DECISIONS_20261109.md).
- 操作与字段 / Operations and fields: [User guide](04_Manuals/USER_GUIDE.md) · [Data dictionary](04_Manuals/DATA_DICTIONARY.md).
- 验收与参考 / Acceptance and reference: [Validation](04_Manuals/VALIDATION.md) · [MAGE review](04_Manuals/MAGE_REFERENCE_REVIEW.md). 正式 `MAGE` 目前留空；研究候选见 `MAGE_candidate_mmol_L`。 / The formal MAGE field is blank pending acceptance. The candidate field is available for research review.
- 开发与发布 / Development and releases: [Contributing](CONTRIBUTING.md) · [Release checklist](04_Manuals/RELEASE.md) · [Changelog](CHANGELOG.md).

真实设备文件、请求清单、患者结果及本地路径配置保留在授权环境。仓库发布代码、规范和合成测试。项目当前未指定开源许可证。

Keep original device files, requests, patient results and site configuration in the authorized environment. The repository distributes code, specifications and synthetic tests. No open-source license has been specified.
