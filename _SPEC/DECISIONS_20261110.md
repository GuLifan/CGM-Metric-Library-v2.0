# 2026-11-10 DRQ系列与完整单CSV

用户批准上一轮工程方案，并更正为取消 NEW_Results.csv、新增 Mode7 胰岛素泵期间表。

- DRQ交付范围为13张窗口CSV、1张FBS CSV和1个14工作表的逐日Excel，每表保留全部请求与原序。
- 固定信息前七列采用住院号、出院日期、入院日期、设备文件名、胰岛素泵开始时间、胰岛素泵停止时间、analysis_id。
- CGM日以首个有效原始正读数为起点。研究窗左闭右开、覆盖率阈值70%，范围指标使用支持分钟。
- Mode7起止为解析后的泵开始和停止，缺失或逆序只阻断该窗口。
- 各窗口独立判断资格，CGM起点不早于出院也可计算全记录、佩戴日及出院后窗口。
- FBS序列表采用住院期内完整05:45—06:15、六槽至少四有效的中位数；列名明确为fasting_cgm_0600。
- 逐日MODD保留窗口内定义，并增加与前一个CGM日精确相差24小时的配对值，两日须合格。D1无前一日值。
- NEW专项表取消后，前三日均值由Mode0_Day1-3的MEAN提供。
- 小数导出保留四位，计算仍用原精度。Excel采用Times New Roman。
- 昨日CML2204_261109_details.zip浓缩为一张CSV，标量可直接读取，明细采用可还原压缩字段。以逐资产SHA-256核对信息完整性。

Detailed definitions and deployment commands are in 04_Manuals/DRQ_DELIVERY.md.
