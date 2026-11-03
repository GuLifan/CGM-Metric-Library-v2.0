# 开发与协作

先读_SPEC中的现行合同。修改医学定义、时间轴或缺失语义前先取得Lifan裁定并写入规范；普通工程修复按现行规则实施。

1. 从已核对的远程分支建立feature分支；避免覆盖他人的未提交修改。
2. 中文docstring说明输入粒度、单位、边界及NA原因；注释解释为什么这样算，避免重复代码字面含义。
3. 为规则变化写独立可手算的合成案例。不得把真实患者文件或标识放入测试。
4. 在03_Codes执行uv sync --frozen、pytest、ruff check及ruff format --check。
5. 审阅git diff和暂存清单，确认无本地配置/患者资料。提交信息与PR说明用英语，说明行为变化和验证。
6. 修改依赖时更新pyproject和uv.lock，重跑测试后用uv export生成requirements.txt。不得手工改锁文件。

推荐小范围PR、至少一次代码审阅；GitHub Actions配置已提供，是否启用分支保护由仓库管理员设置。这里不声称远程设置已完成。
