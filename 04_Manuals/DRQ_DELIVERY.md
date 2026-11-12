# DRQ 结果交付 / DRQ result delivery

当前261112交付采用`deliver`入口，详见[FOLLOWUP_DELIVERY.md](FOLLOWUP_DELIVERY.md)。下文保留261110的15文件布局与命令，供历史重现；当前交付不再包含analysis_id或大段事件JSON。

The current 261112 delivery uses `deliver`; see the follow-up guide. The original 15-file
layout below is retained for reproducibility. Current delivery tables omit analysis IDs and
large event JSON cells.

本功能于 2026-11-10 经用户批准，输出 13 张窗口 CSV、1 张 FBS CSV 和 1 个含 Day 1—14 的 Excel 工作簿。取消 NEW 专项表，新增 Mode7 泵期间窗口。全部输出保留请求清单顺序及每位患者。

Approved on 2026-11-10. The delivery contains 13 window CSV files, one FBS CSV and one Excel workbook with 14 daily sheets. Mode7 covers the insulin pump period. Every delivery table retains the full request order.

## 运行 / Run

从 `03_Codes` 执行 / Run from `03_Codes`.

```sh
uv run --frozen cgm-library drq --request ../_RequestList/request.csv --config configs/site.local.yaml --output-root ../_Outputs --run-id DRQ260723_2204_v2_0_0_261110 --workers 4 --accept-partial
uv run --frozen python tools/validate_drq.py ../_Outputs/DRQ260723_2204_v2_0_0_261110
```

中断后可用同一命令追加 `--resume`。请求、配置、源码摘要必须一致，成功病例的原始文件哈希也会重新核对。单病例数据错误在 audit 中记录，其余病例继续。未预期异常使批次成为 ABORTED。

Append `--resume` to resume an interrupted batch. Request, configuration and source hashes must match. Successful input files are checked again. Patient-level data errors are recorded in audit files. Unexpected errors abort the batch.

## 交付 / Delivery

前七列固定为住院号、出院日期、入院日期、设备文件名、胰岛素泵开始时间、胰岛素泵停止时间、analysis_id。追加的研究信息保留。窗口起止时间与结果字段位于其后。CSV 为 UTF-8 BOM，小数导出为四位；Excel 全表 Times New Roman。交付目录 results 内恰好 15 个文件，audit 每例 JSON 保存覆盖、失败原因、事件事实和来源哈希。

The first seven columns retain the hospital ID, discharge and admission times, device filename, pump start and stop times and analysis ID. Additional study fields follow. Exports round decimal results to four places. Excel uses Times New Roman. The results directory contains exactly 15 files. Per-patient JSON audit records retain coverage, reasons, event facts and source hashes.

旧分组表100个字段及FBS、逐日MODD的映射见 [字段映射](DRQ_LEGACY_FIELD_MAP.csv)。

The linked field map covers all 100 legacy grouped columns, the FBS sequence and the daily MODD field.

Excel 单元格最多容纳 32767 个字符。超过 32000 字符的事件 JSON 拆分至同字段和紧邻的 `__part2`、`__part3` 列。按顺序连接这些字符串即可还原完整 JSON。CSV 保留完整单元格。

Long event JSON is split into the original field and adjacent `__part2`, `__part3` columns at 32000 characters in Excel. Concatenate the parts in order to recover the JSON. CSV retains complete cells.

## 窗口与指标 / Windows and metrics

CGM D1 起点为首个有效正血糖原始时刻，连续每 24 小时为一个 CGM 日。分组起止偏移与旧文件标签对应。全记录起止采用规划组首及末组支持终点。窗口为左闭右开，覆盖率分母包含实际研究范围内的缺失时段。日夜交集分别采用 00:00—06:00 和 06:00—24:00。

CGM day 1 starts at the first valid positive raw observation. Successive CGM days span 24 hours. Grouped windows use the offsets represented by the legacy labels. All-record boundaries use the timeline start and final slot support end. Windows are left-closed and right-open. Coverage denominators include missing time. Night and day intersections are 00:00–06:00 and 06:00–24:00.

Mode7 为泵开始至泵停止。仅日期的开始补12:00，停止沿用普通日期补00:00规则。缺少开始、停止或停止不晚于开始时，Mode7 结果空白，原因记入 audit。其他窗口独立判定。

Mode7 spans pump start to stop. Date-only starts use noon and date-only stops use midnight under the existing anchor contract. Missing or reversed pump anchors leave Mode7 results blank with an audit reason. Other windows are evaluated independently.

所有正式连续指标与次数受窗口70%覆盖率闸门控制。每个昼夜交集的事件独立识别，在合并同类时段时汇总事件事实；日夜汇总指标从对应的有效值和支持分钟重算。夜间最低值列表保留日期、首次原始观测时刻和覆盖率。低于1.8的统计使用窗口内去重后的有效原始正值。

Reported window metrics and counts require 70% coverage. Events are detected independently in each day/night intersection. Pooled period metrics use the corresponding valid readings and supported minutes. Night nadirs retain date, first observed timestamp and coverage. Below-1.8 statistics use deduplicated valid positive raw readings within the window.

逐日表保留 `MODD_mmol_L` 的窗口内配对定义，并增加 `MODD_vs_previous_cgm_day_mmol_L`。后者与前一日相差恰好24小时的规划槽配对，两日均需合格，D1为空。ADRR 依现行自然日交集规则计算。MAGE 正式字段保持当前参考验收闸门，候选值单列。

Daily tables retain within-window MODD and add a previous-CGM-day MODD using exact 24-hour slot pairs. Both daily windows must qualify. Day 1 has no previous-day value. ADRR uses the current calendar-day intersection contract. Formal MAGE remains reference-gated and its candidate is explicitly named.

FBS 表的 D1—D14 定位对应CGM日中的06:00清晨。05:45—06:15须完整落入该日与住院期，六槽至少四槽有效时取中位数。不符合条件时留空。字段为 `cgm_dN__fasting_cgm_0600`。

Each FBS column targets the 06:00 morning within its CGM day. The full 05:45–06:15 interval must lie within that day and the hospitalization. At least four of six slots are required for the median. Otherwise the value is missing.

## 昨日结果包的单CSV / Reversible single-CSV archive

```sh
uv run --frozen cgm-library collapse --archive ../_Outputs/CML2204_261109_details.zip --flat-results ../_Outputs/CML2204_results_261109.csv --output ../_Outputs/CML2204_complete_results_261109.csv
uv run --frozen cgm-library restore --table ../_Outputs/CML2204_complete_results_261109.csv --output ../_Outputs/restored_261109
```

每人一行，前409列为可直接读取的身份信息和标量结果，后两列分别为该患者完整明细以及全包元数据。大字段采用 Base64 和 zlib 压缩。元数据放在第一例行内，保存全部文件路径、表头、顺序、哈希及二进制文件。还原功能重组原CSV行的原始字节，并验证每个资产的 SHA-256。因此昼夜明细、事件、Sparse20候选、异常原始行、时间轴以及配置和审计文件均可完整还原。

Each row contains a patient's scalar results followed by two compressed fields. One carries patient detail fragments and the other carries archive metadata in the first row. Fields use Base64 and zlib. Metadata retains original paths, headers, fragment order, hashes and binary files. Restoration reconstructs the original CSV record bytes and verifies each asset SHA-256, including timeline and raw anomaly evidence.

完整单CSV含有较长的字段，推荐通过本库或支持大字段的CSV读取器使用。Python读取时可先执行 `csv.field_size_limit(2**31 - 1)`。Excel的单元格限制会影响大字段的显示与再保存。

The complete CSV has long fields. Use this library or a CSV reader supporting large fields. Python readers can set `csv.field_size_limit(2**31 - 1)`. Excel's cell limits affect viewing and resaving these fields.

