# maliss 分析进度

## 文件
- ydk: maliss.ydk
- 禁限列表: 2026.10
- 开始时间: 2026-10-19 20:21
- 按新流程重跑: 2026-10-20 11:20（接入 script_facts / combo_scan / hand_matrix）

## 步骤
- [x] Step 1.5: 禁限校验 → banlist_check.txt（2026.10，通过）
- [x] Step 2: 获取原始卡片数据 → deck_raw.csv / deck_raw.json
- [x] Step 3.0: 脚本事实 → script_facts.json（39 张；1 张通常怪兽无脚本）
- [x] Step 3.1: 需求 → 满足者 → combo_candidates.json
- [x] Step 3.1: 动点规则 → combos.json（7 条：5 单卡 + 2 二卡）
- [x] Step 3.2: 穷举起手 → hand_matrix.json（能动 93.25%，死手 6.75%）
- [x] Step 3: 解析卡组结构 → deck_parsed.json
- [x] Step 4: 对局分析 → deck_analysis.json（consistency 7 → 9）
- [x] Step 4.5: 一致性校验 → PASSED（4/4）
- [x] Step 5: 生成报告 → report.md
- [x] Step 5.5: 报告一致性校验 → PASSED（50 条结论全覆盖）

## 完成
- 完成时间: 2026-10-20 11:22
- 注：早期版本只算了「单卡动点开出率 80.03%」，穷举后真实能动率为 93.25%
