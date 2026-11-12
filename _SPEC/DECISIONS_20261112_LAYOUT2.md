# 2026-11-12 布局订正2

用户核对DRQ260723旧逐日表后，批准以下交付调整：

1. Mode0—Mode7分组CSV、CGM逐日以及出院后逐日表，将每个低血糖次数列与其事件时段列相邻排列。沿用v2.0.0命名：`*_n`后为`*_times`。涉及普通、Level2、延长、条件阈值及现有昼夜计数；不将原始低值点QC计数或高血糖计数混作低血糖事件。
2. 多个起止区间用分号分隔，时间保留日期和时分秒，不附时区后缀。次数保持整数。0次对应空时段，观测不足时次数和时段均为空。条件事件按舍入前保存的阈值成员选择，不能从四位显示最低值重新判定。
3. 保留专门低血糖事件CSV，内容不变。
4. 出院后daily以含Day 1—Day 14的Excel作为主要显示，每张sheet保留全部请求及前六列。仍以出院时刻划分24小时，缺少记录的日期不补指标；CSV长表继续作为附加数据。观察末日仍用完整24小时覆盖分母。
5. 只复用已核验的261112计算证据重排，不重算或改变任何原有数值。新批次保存源清单哈希与计算版本引用，原始批次和ZIP保留。测试生成物不写入_Outputs。
6. Mode表共有109列，CGM逐日110列，出院后逐日118列。Excel沿用Times New Roman和四位小数，时段列自动换行。

Layout 2 changes presentation only. The `relayout` command references immutable, hash-verified
patient audit records from a completed 261112 run. Original clinical values and the dedicated
event table remain unchanged. The calculation source and presentation source are recorded
separately in the new manifest.
