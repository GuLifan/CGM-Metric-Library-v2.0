# 结果字段与粒度

| 资产 | 行粒度 | 主要内容 |
|---|---|---|
| patient_window_metrics.csv | 患者×研究窗 | 请求附加列、覆盖、基础指标、事件次数/标签、条件阈值、ADRR/FBS |
| patient_day_night_long.csv | 患者×父窗×日期×日夜 | 子窗独立覆盖、is_partial_period、夜间谷值及首次时刻 |
| event_level_long_table.csv | 患者×窗口×事件 | event_id/type/start/end、nadir/peak、截断、outcome_qualified |
| night_event_level_long_table.csv | 独立夜窗事件 | 同上，不按全天事件起点筛选替代 |
| attd_sparse20_targets.csv | 患者×目标 | 原始取点、目标时刻、距离、缺失原因 |
| attd_sparse5.csv | 患者 | 五项特征与完整性 |
| attd_full7.csv | 患者 | 泵D1/变化、出院前72h三项及24h日夜P5 |
| daily_risk.csv | 患者×窗×日 | is_partial_day、日风险极值、接受状态 |
| patient_status.csv | 每一请求患者 | 成功/部分/错误及泵异常原因 |

血糖为mmol/L；_pct为0–100百分数，_prop为0–1。_n是次数，_any是0/1。缺失用NA，充分无事件用0。时间列为北京时间带偏移ISO时刻。

延长事件的parent_event_id关联普通事件；continuous_low_segments_json保存内部每段的start/end/duration_min，连续子段数不能替代事件数。event_id须结合患者标识和窗口使用，不能跨患者当全局唯一键。

ADRR_complete_days仅用完整自然日且覆盖合格者；adrr_partial_sensitivity_delta=主ADRR−完整日ADRR。无合格完整日为NA并给原因。

MAGE为正式验收字段，当前NA；MAGE_candidate_mmol_L供参考差异核查。不能将候选列重命名为正式列绕过验收。

## 2026-11-09 输出合同

固定资产的完整列和顺序见 `03_Codes/src/cgm_library/contracts/fields.py`。清单使用 `schema_version=2.0-review.1`。空事件、空异常和全患者数据失败时也能按同一表头读取。输入附加列若与生成字段重名，在读取请求时列出冲突。

| 字段 | 含义 |
|---|---|
| valid_minutes、window_minutes、coverage_pct | 有效槽的窗内支持分钟、实际窗长及其比值乘 100。低于覆盖门槛仍输出三项 QC。点数保持单独计数。 |
| TIR_minutes、TAR_minutes、TBR_minutes | 合格窗口三项相加等于 valid_minutes。末槽可贡献小数分钟，各范围百分数的分母为有效支持时长。 |
| first_observed_time、extreme_observed_time | 事件首槽和极值槽各自的首个有效原始观测时间。一分钟聚合值的极值属于整个槽。event_start、nadir_time、peak_time 使用规划槽时刻。 |
| mage_candidate_reason、mage_reason | 候选值的计算原因与正式字段的发布限制分列。 |
| computation_status、warning_codes | 患者计算状态与可并存的质量原因。warning_codes 多值用竖线分隔。泵逆序只影响泵特征。 |
| pump_start_precision、pump_end_precision | 计算表使用 EXACT、MISSING、DATE_ONLY_NOON 或 DATE_ONLY_MIDNIGHT。请求准备表的历史标签 EXACT_TIME、DATE_ONLY_NOON_ON_CALCULATION 分别对应 EXACT、DATE_ONLY_NOON。 |
| raw_qc_reason、qc_reason | 逐行原始清洗原因与重复冲突处理后的原因。 |
| raw_anomalies.csv、is_representative | 重复时刻的所有源行均导出，包括质量正常的有效行。同一时刻仅一行标记为代表。仅一种有效值时可从代表行追溯 Sparse 的 matched_source_row。 |
| duplicate_count、duplicate_conflict_count | 前者按重复时刻中超出首条的原始行数累计。后者按含两种及以上不同有效值的时刻数累计。 |
| ERROR05（过满槽） | patient_status.csv 给出槽编号（从 0 起）、北京时间起止、不同观测时刻数、槽内相邻间隔及全文件去重后间隔中位数。raw_intervals.csv 保留原始行间隔分布，包括重复时刻的零秒间隔。 |
| run_state.json | RUNNING 为进行中或意外中断后尚未收尾，ABORTED 为检测到中止。结束后与 manifest.json 共同核验。ALL_PATIENTS_FAILED 表示全部请求发生数据错误。 |
