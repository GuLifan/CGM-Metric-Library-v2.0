# 2026-11-12 出院后逐日、事件明细与统一患者资格

用户确认1640例完成处理的规则合理，批准出院后逐日结果、事件明细和交付一致性方案，要求先清理_Outputs内测试与无用中间成果。

1. 取消通用计算入口的`cgm_start >= discharge`患者级拒绝。这不是输入错误。有效设备文件允许从出院后开始，住院及出院前窗口独立判断覆盖率；无足够数据仍为空。非法时间及出院不晚于入院继续按原错误处理。
2. 出院后Dn为`[discharge + 24*(n-1)小时, discharge + 24*n小时)`。D1—D7保留全部请求，D8起延续至每例记录结束所处的日。结束恰在边界不额外生成一天。末日覆盖分母保持完整24小时，不裁成记录长度。
3. 沿用原清洗、规划槽、70%覆盖、昼夜交集和未舍入阈值规则。昼夜仍按00:00—06:00、06:00—24:00。后续日不输出不适用的住院FBS-CV和窗内MODD；前一出院后日的MODD要求两日合格，采用精确24小时配对，D1为空。
4. Full7和Sparse5保留原锚点和4/8/12取点规则。日指标复用相同方法，不重新定义泵D1/D3或出院前特征，也不引入未经批准的逐日Sparse方案。
5. 所有Mode、CGM逐日、NewMetric、Full7、Sparse5、患者状态和新增出院后逐日结果由同一患者计算记录生成，禁止新旧批次直接混装为同一版。
6. 低血糖明细为患者×窗口×时段×事件类型×事件，每行含起止、经过时长、低值支持分钟、最低值及其时刻、截断标记。只列对应时段合格的正式事件；不合格事实保存在audit。普通事件和Level2、延长类型可嵌套，重叠窗口不相加。HYPO_COND由普通事件舍入前nadir判定，另留阈值成员，避免四位显示影响次数核验。
7. 所有时间按本项目本地钟点解释，交付时间不附时区后缀。计算内部仍保留时区感知对象。固定前六列保留，交付表不含analysis_id。小数四位half-up，整数次数保留整数、零保留、缺失留空。Excel使用Times New Roman。
8. 测试生成物不再写入_Outputs。清理记录存于02_Logs/outputs_cleanup_261112.json。真实结果、交付包、比较报告与异常病例证据保留；必要执行资料归入历史批次provenance。

The `deliver` command implements this revision. The historical `drq` command retains the legacy
15-file layout for reproducibility, while both computation entries accept post-discharge-only
recordings. The revised delivery is validated with `tools/validate_delivery.py`.
