# 2026-11-14 布局订正3 / Delivery layout 3

按用户批准的修改执行：

1. Mode0—Mode7及两种daily的每个低血糖_times单元格，每次事件采用`开始 - 结束 = 最低值`；同格多次事件用`; `分隔。最低值单位mmol/L，四位half-up小数，沿用对应事件事实及未舍入条件阈值成员。保留完整日期和时分秒，不加时区标注。
2. 出院时刻切分的daily新增第一张“出院前24h”，范围[T−24h,T)。直接复用pre24h已有计算证据，post_discharge_day和前一出院日MODD留空。后续Day 1—Day 14不变，均为从出院时刻推移的24小时区间；每页2204例，共15页。CSV长表仍仅为出院后逐日数据。
3. 每个Mode表和两个daily每个sheet均保留有且仅有一列全窗最低值global_min（mmol/L）。该列原本已存在，核验并明确含义，不重复增加同义列。保留夜间/白天最低值列，两者不能替代全窗global_min。覆盖不合格的正式最低值继续为空。
4. 专门低血糖事件表保留，内容应与布局订正2逐字节相同。所有原始计算值、人数、窗口边界不变；只增加事件最低值文本和已有pre24h的显示位置。
5. 新结果目录CML2204_261112_layout3，交付包DRQ261112_CML2.0_2204_layout3.zip；原目录及ZIP保留。版本保持2.0.0，沿用261112批次标签，布局版本递增为3。
6. 更新中英双语README、部署说明、生成包内README、更新记录和核验工具；验证通过后推送源码和文档至GitHub，患者数据不入仓库。

Layout 3 enriches readable event text with event-specific nadirs and adds a pre-discharge
24h sheet before the 14 discharge-anchored days. It verifies the existing whole-window
global_min throughout Mode and daily output. It changes no calculation, eligibility or
conditional membership. Original metrics and event detail bytes must remain unchanged.
Export uses hash-verified calculation evidence; keep the original audit directory.
