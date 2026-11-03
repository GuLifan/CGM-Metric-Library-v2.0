# 验收合同

| 规则 | 必须证明的结果 | 当前证据位置 |
|---|---|---|
| 一分钟五点/四零一值 | 均值、组首时间、独立原始Sparse | tests/unit/test_timeline_rebuild.py |
| 五分钟同槽冲突 | 整槽NA、原始证据保留 | test_timeline_rebuild.py |
| 120低/5正常/120低 | 1父事件、2连续段，各120分钟 | test_meeting_rules.py |
| 15分钟恢复 | 两次独立事件 | test_meeting_rules.py |
| 阈值恰好3.0 | 不计低于3.0；合格无事件0，不足NA | test_meeting_rules.py |
| 局部自然日 | 交集分母、部分日标记、完整日ADRR另列 | test_meeting_rules.py |
| 停止≤开始 | 只空泵指标，Sparse和非泵指标保留 | test_meeting_rules.py |
| 来源cleaned | 拒绝参与计算 | test_meeting_rules.py |
| 批次某患者文件缺失 | 其他患者继续、全批PARTIAL | test_partial_batch_rebuild.py |
| MAGE | 全窗SD严格大于、R差异解释及参考证据 | tools/compare_mage_reference.py；未正式验收 |

独立验收还应核对：请求附加列保留、理论点数与有效点数、TIR+TAR+TBR分钟总和、每人Sparse20目标数、输出哈希与患者总数。
正式MAGE不能使用候选列冒充；整个项目发布必须明确参考验证和真实批次状态。最终患者批次不属于本次无真实数据工程搭建的运行证据。
