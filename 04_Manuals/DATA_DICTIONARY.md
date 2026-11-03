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
