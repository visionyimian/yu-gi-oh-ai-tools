# 卡组分析产物

这里存放跑完整条 pipeline 之后的产物快照。**不属于代码，因此单独放在 `analyses` 分支，不进 `main`。**

## 为什么单独一个分支

- 这些文件是**生成物**，每次重跑都会变，放进 `main` 会让 diff 充满无关变更
- 但它们又是唯一无法重建的资产（分析结论、做场账本），不能只留一份在磁盘上

## 目录

| 目录 | 卡组 | 说明 |
|---|---|---|
| `maliss/` | 码丽丝（42 张旧版） | 第一版分析，能动率 93.25%（含人工复核的动点） |
| `test-deck/` | 阿匹卜／王家的神殿 | 仓库自带示例，禁限校验发现 2 处违规（2026.10） |
| `奥艺码丽丝/` | 码丽丝（40 张新版） | 主线样本：24 步场值账本、8 个终场选项、`baseline.md` |

每个目录下的文件：

| 文件 | 内容 |
|---|---|
| `banlist_check.txt` | 禁限校验结果 |
| `deck_raw.csv` / `deck_raw.json` | 从 ydk 还原出的卡片数据 |
| `script_facts.json` | 卡脚本读出的硬事实（OPT / kind / targets / has_cost）|
| `combo_candidates.json` | 需求 → 满足者扫描 |
| `combos.json` | 动点规则（自动推导） |
| `hand_matrix.json` | 穷举起手的能动率 / 死手率 |
| `deck_parsed.json` | 结构化解析（含 `script` 块、`hand_matrix`）|
| `deck_analysis.json` | 对局分析（终场、弱点、chokepoint、做场线）|
| `report.md` | 人类可读报告 |
| `TODO.md` | 流程进度 |
| `baseline.md` | 仅奥艺码丽丝：接入模拟器前的假设清单 |

## 怎么复现

```bash
python skills/ocg-banlist/scripts/fetch_banlist.py --check {deck}.ydk > {A}/banlist_check.txt
ygo-db-cli get-cards-by-ydk -i {deck}.ydk -o {A}/deck_raw.csv
ygo-db-cli get-cards-by-ydk -i {deck}.ydk --format json -o {A}/deck_raw.json
python skills/deck-parser/scripts/script_facts.py --ydk {deck}.ydk --cache .cache/ygopro-scripts \
  --cdb {cards.cdb} -o {A}/script_facts.json
python skills/deck-parser/scripts/combo_scan.py {A}/deck_raw.json -o {A}/combo_candidates.json
python skills/deck-parser/scripts/hand_matrix.py {A}/deck_raw.json --derive \
  --facts {A}/script_facts.json --candidates {A}/combo_candidates.json \
  --cdb {cards.cdb} --write-rules {A}/combos.json -o {A}/hand_matrix.json
python skills/ygo-deck-analyze/scripts/verify.py {A} --cdb {cards.cdb}
```

`deck_parsed.json` 和 `deck_analysis.json` 之间还有判断环节（分类、终场、做场线），
那部分由 agent 按 `SKILL.md` 产出，`check_parse.py` 负责校验一致性。

## 已知局限

- 能动率是**自动推导的上界**，未逐条复核
- 做场线的 `verified` 都是 `false`——顺序按卡面推导，没在 ygopro-core 里跑过
- 六维评分的「上限」「抗性」仍属判断
