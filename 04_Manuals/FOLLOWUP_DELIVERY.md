# 261112交付与部署 / Follow-up delivery and deployment

当前为布局订正3（2026-11-14），计算库版本仍为2.0.0，沿用261112批次标签。Mode0—Mode7和两类daily的低血糖次数后，紧邻_times列，每次事件显示：

`2024-06-21 22:51:18 - 2024-06-21 23:31:18 = 3.2000; 2024-06-21 23:46:18 - 2024-06-22 00:41:18 = 3.4000`

Layout 3 enriches each adjacent event interval with that event's nadir (mmol/L). Entries
use full dates and seconds, no timezone suffix, semicolon separators, and four-place half-up
rounding. Typed, conditional and day/night events use the same saved facts as their counts.
A zero count retains a blank event cell; missing counts and event cells remain blank.
The dedicated Hypoglycemia_Events.csv is retained without changes.

出院时间切分daily的文件名仍为AfterDischarge_Daily_D1-14.xlsx，但现在含15页：第一张“出院前24h”为[T−24h,T)，后续Day 1—Day 14为[T+24×(n−1)h,T+24×n h)。每页保留2204例。出院前24h直接复用pre24h计算结果，post_discharge_day留空，前一出院日MODD也留空；未产生有效观察时不填造指标。CSV长表继续只含出院后逐日结果，行数与原版一致。

The discharge-anchored workbook now has 15 sheets: pre-discharge 24h [T−24h,T), then
Day 1–Day 14 with the original discharge-based 24-hour boundaries. Every sheet retains the
entire cohort. The new sheet reuses pre24h, leaves post_discharge_day and previous-discharge-day
MODD blank, and keeps existing coverage and missing-value rules. The long CSV remains
post-discharge only. The separate CGM daily workbook retains 14 sheets anchored at first CGM.

每个Mode表和两个daily的每张sheet均有且仅有一列global_min，表示当前整个时间窗的有效CGM最低值（mmol/L），无低血糖事件时也可有值。这一列原本已经存在，本次核验保留，避免重复列。夜间/白天前缀的最低值仅代表对应时段，不替代global_min。全局最低值遵循原有70%覆盖率门槛，数据不足仍留空。单次事件的最低值仅对应各自事件，不能替代全窗最低值。

Each Mode table and every sheet in both daily workbooks contains exactly one global_min
(mmol/L), the minimum valid CGM value across the entire window, even when there are no
hypoglycemia events. This existing field is verified rather than duplicated. Period-prefixed
minima cover their respective period. All minima retain the original 70% coverage gate;
unavailable values stay blank. Event nadirs and window-wide minima refer to different ranges.

Excel uses Times New Roman, wrapped event cells and four-place numeric formatting.
CSV uses UTF-8 with BOM. The first six request fields remain unchanged; analysis_id is excluded.

已有批次可只重导交付表，无需重新计算指标。新目录引用经哈希核验的原始audit，必须同时保留原批次目录。原ZIP也保留。

For an existing run, re-export from hash-verified audit evidence without recalculating
metrics. Retain the original calculation directory and previous ZIP for traceability.
Run the following from 03_Codes:

```sh
uv run --frozen cgm-library relayout --source-run ../_Outputs/CML2204_261112 --output-root ../_Outputs --run-id CML2204_261112_layout3 --prefix DRQ261112_CML2.0_2204
uv run --frozen python tools/validate_delivery.py ../_Outputs/CML2204_261112_layout3
uv run --frozen python tools/compare_delivery_revision.py ../_Outputs/DRQ261112_CML2.0_2204_layout2.zip ../_Outputs/CML2204_261112_layout3 ../_Outputs/CML2204_261112_layout2 --report ../02_Logs/layout3_comparison_261112.json
uv run --frozen python tools/package_delivery.py ../_Outputs/CML2204_261112_layout3 ../_Outputs/DRQ261112_CML2.0_2204_layout3.zip
```

本版将Mode、CGM逐日、ATTD特征、NewMetric与新增结果统一到同一次逐患者计算。包版本仍为2.0.0，订正标识261112。

This revision generates Mode tables, CGM daily results, ATTD features, NewMetric and follow-up
results from the same patient calculation. Package version remains 2.0.0; revision is 261112.

## 运行 / Run

完成根README所述uv部署后，从03_Codes执行。真实输入清单和数据源配置保持本地。

After following the root README deployment steps, run from 03_Codes. Keep real requests and
source configuration local.

```sh
uv run --frozen cgm-library deliver --request ../_RequestList/request.csv --config configs/site.local.yaml --output-root ../_Outputs --run-id CML2204_261112 --prefix DRQ261112_CML2.0_2204 --workers 4 --accept-partial
uv run --frozen python tools/validate_delivery.py ../_Outputs/CML2204_261112
uv run --frozen python tools/package_delivery.py ../_Outputs/CML2204_261112 ../_Outputs/DRQ261112_CML2.0_2204.zip
```

中断可追加--resume，请求、配置、源码和文件前缀必须一致。批次目录保存逐例audit、请求/配置快照、患者状态和输出哈希；results为交付内容。请使用新批次名，不覆盖历史结果。旧drq命令保留261110布局。

Append --resume after interruption. Request, config, code and prefix must remain unchanged.
The run directory retains audit records, input snapshots, outcomes and asset hashes. The
results subdirectory contains deliverables. Use a fresh run ID. The old drq command retains
the 261110 layout.

打包工具只收录results内的交付内容，并逐文件验证压缩包内字节与批次哈希一致；原始设备文件和内部audit不打入甲方结果包。ZIP旁同时保存SHA-256校验文件。

The packaging tool includes readable results only and verifies every archived asset against
the run manifest. Original device files and internal audit are excluded from the client
package. A SHA-256 checksum is saved alongside the ZIP.

## 表格与粒度 / Tables and grain

| 输出 / Output | 粒度与用途 / Grain and purpose |
|---|---|
| Mode0—Mode7 CSV | 每例每窗口一行；统一109列，含21组次数/时段列。 / One row per request and window; 109 columns including 21 adjacent count/time pairs. |
| Mode0_Daily_D1-14.xlsx | 14张CGM日工作表，110列；起点为首个有效CGM时刻。 / Fourteen CGM-day sheets with 110 columns, starting at the first valid reading. |
| AfterDischarge_Daily_D1-14.xlsx | 15张表：出院前24h及出院后Day 1—Day 14；每页118列，保留全部患者、全窗global_min及缺失原因。 / Fifteen 118-column sheets: pre-discharge 24h and 14 follow-up days, retaining the cohort, window minima and missing-day reasons. |
| AfterDischarge_Daily_Results.csv | 每例每出院后日一行；含覆盖与原因。 / One row per request and follow-up day, including quality and reasons. |
| Hypoglycemia_Events.csv | 每例每窗口每时段每个指定类型事件一行。 / One row per patient, window, period and typed event. |
| Window_Quality.csv | 每例窗口与全天、昼、夜资格；区分零事件和缺测。 / Per-window and period eligibility, distinguishing zero events from missing data. |
| NewMetric_Results.csv | 每例一行390列，含六窗标量与Full7、Sparse5。 / One row per request, 390 columns of six-window scalars and ATTD features. |
| NewMetric_Summary.xlsx | 说明、患者总览、未计算病例、Full7、Sparse5。 / Notes, overview, failed cases and ATTD sheets. |
| Patient_Summary.csv | Excel患者总览的独立CSV。 / Standalone CSV of the workbook overview. |
| FBS_24H_D1-14_Results.csv | 沿用住院期清晨定义。 / Original hospitalized morning definition. |
| 2204_PatientStatus.csv、2204_RequestList.csv | 患者状态及六列输入信息。 / Outcomes and six-column request identity. |

## 窗口与指标 / Window and metric rules

出院后Dn采用完整24小时左闭右开窗。固定保留D1—D7，继续至实际记录结束所处日。最后一天仍以1440分钟作分母；无数据或不足70%时保留行、原因和覆盖，正式指标留空。有效观测充分但没有事件为0。独立昼夜交集按固定钟点重算，不将出院后的前六小时称为夜间。

Follow-up days use left-closed, right-open 24-hour windows. Days 1–7 are retained and later
days extend to the record end. The last day still uses 1440 minutes as its denominator.
Insufficient data retain quality evidence but no formal metric. Qualified observation with
no event is zero. Day/night intersections use fixed clock times.

新增日表省略住院FBS-CV和单日窗内MODD，其余适用指标与精简daily相同。MODD_vs_previous_discharge_day_mmol_L比较相邻合格出院后日中相差恰好24小时的规划槽，D1为空。ATTD固定泵/出院前锚点与Sparse原始取点不变。

The follow-up daily table omits inpatient fasting CV and within-day MODD. Its separately
named previous-day MODD uses exact 24-hour slot pairs and requires both days to qualify.
ATTD pump/pre-discharge anchors and sparse raw sampling remain unchanged.

## 事件解释 / Event interpretation

普通低血糖与Level2分别使用现行3.9和3.0阈值及15分钟启动/恢复规则；延长类型沿用120分钟连续低值规则。事件时长为event_end−event_start，不等同于condition_minutes。窗口边界或缺测截断以左右标记和原因表示，不能宣称全部事件均观测到完整恢复。

Ordinary and Level 2 hypoglycemia retain their 3.9 and 3.0 thresholds and 15-minute
start/recovery rules. Extended types retain the 120-minute continuous-low rule. Elapsed
duration differs from below-threshold minutes. Censor flags identify incomplete observation.

阈值累计次数仅来自普通事件最低值。hypo_cond_thresholds保存舍入前严格阈值成员，以竖线分隔，如3.3|3.4|3.5|3.6|3.7|3.8。Level2和延长类型可与普通事件嵌套；不同窗口和时段也可重叠，不得直接累加为独立事件总数。

Conditional counts use ordinary-event nadirs. Pipe-separated threshold membership is
determined before rounding. Event types, periods and windows can overlap and must not be
summed as independent episodes.

交付时间显示日期和时分秒，不附时区后缀。小数四位half-up；CSV无字体元数据，Excel使用Times New Roman。analysis_id仅供内部追溯，不出现在交付表格。

Delivered times show local date and clock time without suffixes. Decimals use four-place
half-up rounding. CSV has no font metadata; Excel uses Times New Roman. analysis_id is
internal and excluded from delivered tables.

## 1638与1640历史差异 / Historical eligibility difference

11月9日旧入口将首个有效CGM不早于出院判为整例ERROR04，11月10日DRQ允许按窗口继续计算。因此清单第978、1042例在两套结果中状态不同。相同输入和共同窗口的计算值已经逐项核对。261112撤销旧入口的整例限制，并让各表从同一记录生成；不会强行为没有观测的住院窗口补值。

The November 9 entry rejected an entire file when CGM started at or after discharge. The
November 10 DRQ entry evaluated windows independently. This affected requests 978 and 1042.
Revision 261112 removes the global rejection and generates all tables from the same record.
Unobserved inpatient windows remain missing.
