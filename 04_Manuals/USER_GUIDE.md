# 本地操作

安装uv后在03_Codes运行uv sync --frozen，环境固定在03_Codes/.venv。运行pytest检查本机环境。可用--help查看参数。

先运行tools/run_synthetic_pilot.py建立无患者信息的示范资产，再准备site.local.yaml与新版请求表。路径相对配置文件目录解析；批次日期范围左闭右开，每个出院日期必须对应唯一来源。拒绝_cleaned来源，不自动寻找“相似文件”。

时间均为北京时间。仅日期的入出院补00:00，泵开始补12:00。停止≤开始时只空泵指标，日志有PUMP_STOP_NOT_AFTER_START；其余指标继续。缺停止时间单独标QC，不能擅自判断逆序。

查看输出顺序：manifest.json确认患者总数和状态；logs/patient_status.csv查看错误；qc_and_coverage查看覆盖及原始异常；metric_outputs查看长表、事件和Sparse证据。MAGE_candidate_mmol_L不是正式MAGE。

ERROR01文件未找到；ERROR02身份/来源不唯一；ERROR03结构或配置错误；ERROR04时间无法解析；ERROR05单位/频率/来源不允许；ERROR99其他已捕获异常。记录错误后其余患者继续。PARTIAL表示未完整验收，不能改标签当SUCCESS。

复算必须使用新的run_id。请保留输入版本和旧结果，不能直接编辑计算结果修正源错误。
