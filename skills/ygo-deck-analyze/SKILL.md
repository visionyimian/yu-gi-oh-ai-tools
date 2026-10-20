---
name: ygo-deck-analyze
description: 游戏王卡组完整分析流程的 parent skill。当用户提供 .ydk 文件并要求分析卡组时使用此 skill。负责建立工作目录、追踪进度、按顺序调用 deck-parser 和 deck-analyzer，并生成最终人类可读报告。触发词：分析卡组、.ydk、卡组分析、帮我看看这套卡。
---

# ygo-deck-analyze

## 职责

这是整个分析流程的协调者（orchestrator）。

负责：
- 建立工作目录和进度追踪文件
- 按顺序执行四个步骤
- 每步完成后将产物 dump 成文件
- 如果某步失败，记录断点，下次可从断点恢复
- 生成最终人类可读报告

不负责：
- 卡片信息获取（由 deck-parser 处理）
- 对局分析判断（由 deck-analyzer 处理）

---

## 工作目录结构

每个卡组建立独立目录，命名规则为 `{ydk文件名}_analysis/`。

```
{deck_name}_analysis/
├── TODO.md              # 进度追踪，每步完成后更新
├── banlist_check.txt    # Step 1.5 产物：禁限校验结果（含所用列表期号）
├── deck_raw.csv         # Step 2 产物：CLI 原始返回数据（CSV格式）
├── deck_raw.json        # Step 2 产物：同一份数据的 JSON 版（combo_scan 需要 archetypes 字段）
├── script_facts.json    # Step 3 产物：效果硬事实（script_facts 输出）
├── combo_candidates.json # Step 3 产物：需求 → 满足者候选（combo_scan 输出）
├── combos.json          # Step 3 产物：人工确认后的动点规则（hand_matrix 输入）
├── deck_parsed.json     # Step 3 产物：deck-parser 输出
├── deck_analysis.json   # Step 4 产物：deck-analyzer 输出
└── report.md            # Step 5 产物：最终人类可读报告
```

---

## 断点恢复逻辑

开始前，先检查工作目录是否已存在：

- 如果目录不存在 → 全新开始，执行 Step 1
- 如果目录存在，读取 `TODO.md` → 找到第一个未完成的步骤，从该步骤继续
- 如果某个产物文件存在且非空 → 该步骤视为已完成，跳过

---

## 执行流程

### Step 1 — 初始化工作目录

1. 根据 `.ydk` 文件名创建工作目录，并创建 `TODO.md`

```bash
mkdir -p {deck_name}_analysis && touch {deck_name}_analysis/TODO.md
```

2. 写 `TODO.md`，内容如下：

```markdown
# {deck_name} 分析进度

## 文件
- ydk: {ydk_filename}
- 禁限列表: {banlist}（校验时填写）
- 开始时间: {timestamp}

## 步骤
- [ ] Step 1.5: 禁限校验 → banlist_check.txt
- [ ] Step 2: 获取原始卡片数据 → deck_raw.csv / deck_raw.json
- [ ] Step 3: 解析卡组结构 → deck_parsed.json（含 hand_matrix）
- [ ] Step 4: 对局分析 → deck_analysis.json
- [ ] Step 4.5: 一致性校验 → PASSED / FAILED+修正
- [ ] Step 5: 生成报告 → report.md
- [ ] Step 5.5: 报告一致性校验 → PASSED / FAILED+补充
- [ ] Step 5.6: 交付前总校验 → VERIFY PASSED
```

3. 在 `TODO.md` 中将 Step 1.5 标记为进行中。

---

### Step 1.5 — 禁限校验（Legality）

在花时间解析之前，先确认这副牌在目标环境里能不能打。

以下命令**在仓库根目录执行**，`{analysis}` 指 `{deck_name}_analysis/`：

```bash
python skills/ocg-banlist/scripts/fetch_banlist.py --check {ydk} > {analysis}/banlist_check.txt 2>&1
echo "exit=$?" >> {analysis}/banlist_check.txt
```

（若工作目录就在 `skills/` 下，改成 `python ../ocg-banlist/scripts/fetch_banlist.py` 并去掉 `skills/` 前缀即可。）

- 默认对照**最新 OCG 列表**；用户指定 TCG、或卡组明显是 TCG 环境时加 `--tcg`
- 需要固定某一期时加 `--list 2026.10`
- `banlist_check.txt` 里必须留有**所用列表的期号**（例如 `2026.10`），否则报告无法复现

**判定**：退出码 `0` = 通过；`1` = 有超限。

禁限不通过**不中止流程**——用户可能就是在测一副违规卡组，或者打的是别的规则。处理方式：

1. 在 `TODO.md` 里标 `[!] Step 1.5: 禁限校验 → N 处超限（列表 {banlist}）`
2. 在报告开头的「构筑合法性」里写明
3. 继续执行 Step 2

只有当卡库能正常查询、但禁限脚本自身报错（网络失败、列表名不存在）时，才算这一步失败，按「错误处理」中止。

完成后更新 `TODO.md`：
```markdown
- [x] Step 1.5: 禁限校验 → 通过（列表 2026.10）
```

---

### Step 2 — 获取原始卡片数据

使用 `ygo-db-cli` CLI 工具获取卡片信息：

```bash
ygo-db-cli get-cards-by-ydk -i {ydk文件路径} -o deck_raw.csv
```

CLI 工具会将数据（CSV格式）完整 dump 到 `deck_raw.csv`。

> 保存原始数据的目的：如果后续解析逻辑有问题，可以直接重跑解析步骤，不需要重新调用 CLI。

完成后更新 `TODO.md`：
```markdown
- [x] Step 1: 获取原始卡片数据 → deck_raw.csv
```

---

### Step 3 — 解析卡组结构

读取 `deck_raw.csv`，调用 `deck-parser` skill 进行卡组结构解析。

输入：`deck_raw.csv`
输出：按 `deck-parser` skill 定义的 JSON schema 生成结果，dump 到 `deck_parsed.json`。

#### 3.0 脚本事实（必做）

先跑 `deck-parser` 的 Step 0，把效果硬事实落盘：

```bash
python ../deck-parser/scripts/script_facts.py --ydk {ydk} --cache .cache/ygopro-scripts \
  --cdb {cards.cdb} -o script_facts.json
```

`deck_parsed.json` 的 `once_per_turn_type` 必须与 `script_facts.json` 的 `opt` 一致；脚本给 `custom` 的卡必须人工复核并标注 `once_per_turn_source: "script_custom"`。

#### 3.1 动点矩阵（必做，不能只靠读卡）

同样的数据再导一份 JSON（`combo_scan` 需要 `archetypes` 字段）：

```bash
ygo-db-cli get-cards-by-ydk -i {ydk} --format json -o deck_raw.json
python ../deck-parser/scripts/combo_scan.py deck_raw.json -o combo_candidates.json
```

按 `combo_scan` 的候选表逐条验证，把成立的二卡动点写成 `combos.json`，然后穷举起手：

```bash
python ../deck-parser/scripts/hand_matrix.py deck_raw.json combos.json
```

把结果（`one_card_rate` / `two_card_rate` / `startable_rate` / `dead_rate`）回填进 `deck_parsed.json` 的 `hand_matrix`。

> **判断依据**：只有走完确实能产出有效场面（至少一次有意义的额外卡组召唤）才算动点。
> 「两张怪站着」不算。额外卡组怪兽不能写进 `combos.json` 的卡名，用 `link1_material` 之类的谓词表达。

#### 3.2 死手率闸门

`dead_rate` > 15% 时**不得进入 Step 4**：先回 3.1 复查是否漏了二卡动点（尤其是额外卡组里的 Link-1）。
确认无误后再继续，并在 `TODO.md` 里写明「已复查，死手率 X% 为真实值」。

完成后更新 `TODO.md`：
```markdown
- [x] Step 2: 解析卡组结构 → deck_parsed.json（能动率 X%，死手率 Y%）
```

---

### Step 4 — 对局分析

读取 `deck_raw.csv` 和 `deck_parsed.json`，调用 `deck-analyzer` skill 进行完整对局分析。

输入：`deck_raw.csv` + `deck_parsed.json`
输出：按 `deck-analyzer` skill 定义的 JSON schema 生成结果，dump 到 `deck_analysis.json`。

完成后更新 `TODO.md`：
```markdown
- [x] Step 3: 对局分析 → deck_analysis.json
```

---

### Step 4.5 — 一致性校验（Validation）

在生成报告前跑脚本。**退出码非 0 就不得进入 Step 5，必须先修正。**

```bash
python skills/ygo-deck-analyze/scripts/check_parse.py \
  --parsed {analysis}/deck_parsed.json \
  --analysis {analysis}/deck_analysis.json \
  --matrix {analysis}/hand_matrix.json \
  --facts {analysis}/script_facts.json \
  --cdb {cards.cdb}
```

它检查四件事：

| 检查 | 含义 | 不过时怎么办 |
|---|---|---|
| **endboard 覆盖** | parser 标为终场的卡（`maindeck_endboard` ＋ `extradeck_monsters` 中 role 为 `endboard`/`both` 的），analyzer 的 `typical_endboard` 里必须都出现 | 回 deck-analyzer 的 Step 2 补分析 |
| **hand_matrix** | `deck_parsed.json` 里的能动率/死手率必须与穷举结果一致 | 重新回填，不要手改数字 |
| **脚本事实一致性** | `once_per_turn_type` 必须等于脚本的 `opt`；`custom` 的卡必须标 `once_per_turn_source: "script_custom"` | 看 Step 0 的 `custom_evidence` 重新判定 |
| **script 块完整性** | 有脚本的卡必须带 `script: {kinds, targets, has_cost, no_miss_timing}` 且与脚本一致 | 说明没做 Step 0，回去补 |

脚本覆盖不到、仍需人工确认的两件事：

1. **死手率闸门**：脚本在 `dead_rate > 15%` 时会打 `[WARN]`。这时必须回 Step 3.1 复查是否漏了二卡动点（尤其是额外卡组里的 Link-1），并在 `TODO.md` 里写明「已复查，死手率 X% 为真实值」。
2. **需求覆盖**：卡组里只要有卡的文本含「连接怪兽特殊召唤的场合」或「被除外的场合」，`combo_starters` 就必须逐条说明「最便宜的触发器是什么」，或者说明为什么不成立。

完成后更新 `TODO.md`：
```markdown
- [x] Step 4.5: 一致性校验 → PASSED（4 项）/ FAILED+修正
```

---

### Step 5 — 生成人类可读报告

读取 `deck_parsed.json` 和 `deck_analysis.json`，生成自然语言分析报告，dump 到 `report.md`。

报告格式见下方「报告模板」。

### Step 5.5 — 报告一致性校验

报告是手写的，很容易漏掉表格里的一两行。用脚本核对：

```bash
python skills/ygo-deck-analyze/scripts/check_report.py {analysis}/deck_analysis.json {analysis}/report.md
```

它把 JSON 里**标识性文字**（终场卡名、解场卡名、手坑名、chokepoint 卡名、后攻工具、六维键）当作必现清单，逐项在报告里查找；`reason` 这类自由文本不参与比对。

- 退出码 `0` → 每条结论都出现了
- 退出码 `1` → 会列出哪个分区缺了哪些条目，**补完再交付**

> 实测：码丽丝那份报告第一遍跑就抓出 4 处遗漏（3 张备选终场 + 1 个 chokepoint 用了简称）。

完成后更新 `TODO.md`：
```markdown
- [x] Step 5: 生成报告 → report.md
- [x] Step 5.5: 报告一致性校验 → PASSED（N 条结论全覆盖）
```

### Step 5.6 — 交付前总校验

一条命令把前面所有校验跑完：

```bash
python skills/ygo-deck-analyze/scripts/verify.py {analysis} --cdb {cards.cdb}
```

| 组 | 检查 |
|---|---|
| 1 | 产物完整性：11 个文件都在且非空 |
| 2 | 流程完成度：`TODO.md` 里没有未勾选的步骤 |
| 3 | Step 4.5：调用 `check_parse.py`（4 项） |
| 4 | Step 5.5：调用 `check_report.py` |

- `[VERIFY PASSED]` 才交付
- `--skip-report` 用于报告还没写的中间状态
- 不联网；禁限校验不重跑，只检查 `banlist_check.txt` 是否已生成

完成后更新 `TODO.md`：
```markdown
- [x] Step 5.6: 交付前总校验 → VERIFY PASSED（4 组）

## 完成
- 完成时间: {timestamp}
```

---

## 报告模板

`report.md` 必须使用以下结构：

```markdown
# {archetype} 卡组分析报告

**卡组类型**：{deck_type} ｜ **操作难度**：{difficulty}  
**主卡组**：{main}张 ｜ **额外卡组**：{extra}张 ｜ **副卡组**：{side}张  
**禁限校验**：{banlist_status}

---

## 卡组概览

{用2-3句话描述卡组的核心机制和风格}

**主引擎**：{primary_engine}  
**副引擎 / Package**：{secondary_engines}

---

## 构筑合法性

{对照的列表期号 + 结论。通过时一句话带过；有超限时逐条列出：卡名 / 实际张数 / 限制数。
若用户明确说「按 TCG 打」或「不管禁限」，在这里注明前提。}

---

## 起手稳定性

- 能动率 **{startable_rate}**（穷举全部 5 张手牌得出）／死手率 {dead_rate}
- 其中单卡动点 {one_card_rate}、二卡动点 {two_card_rate}
- Starter（{starter_total_copies}张）开出率：刚好1张 {starter_exactly_1} ／ 刚好2张 {starter_exactly_2} ／ 至少1张 {starter_at_least_1} ／ 至少2张 {starter_at_least_2}
- 手坑（{handtrap_total_copies}张）开出率：刚好1张 {handtrap_exactly_1} ／ 刚好2张 {handtrap_exactly_2} ／ 至少1张 {handtrap_at_least_1} ／ 至少2张 {handtrap_at_least_2}

{用1-2句话说明稳定性的含义，例如"平均每4手有3手能正常启动"。如果存在二卡动点，说明是哪两组牌配哪几类身体。}

---

## 典型先攻终场

**终场类型**：{board_type}  
**妨碍数量**：{interaction_count}

| 终场卡片 | 作用 |
|---|---|

**抗性**：{抗性说明}  
**自锁风险**：{self_lock_risk}

> 如果终场类型为 `RESOURCE_DENIAL_BOARD`，在此说明对手的哪些资源会被破坏，以及通常在第几回合让对手断粮。

---

## 展开多样性

**整体评价**：{overall_verdict} — {overall_reason}

| 干扰类型 | 应对能力 | 说明 |
|---|---|---|
{干扰类型列表}

---

## 终场弱点

**最大威胁**：{biggest_threat} — {biggest_threat_reason}

**盘面突破手段**

| 去除手段 | 有效程度 | 原因 |
|---|---|---|
{盘面突破列表}

**机制封锁手段**

| 封锁类型 | 有效程度 | 原因 |
|---|---|---|
{机制封锁列表}

---

## 系统性弱点

{对每个系统性弱点用一段话说明：依赖什么机制、哪些卡能针对、被针对后还能做什么、这类卡在当前 meta 中是否常见}

---

## 手坑敏感度

| 手坑 | 影响程度 | 被打断时机 |
|---|---|---|
{手坑列表}

---

## 关键 Chokepoint

{对每个 chokepoint 用一段话说明：是什么、为什么关键、怕什么、有没有替代路}

---

## 后攻能力

{用自然语言描述后攻突破手段、效率、突破后余力、OTK 潜力}

---

## 资源续航

{用自然语言描述检索机制、墓地循环、面对增殖G的策略、长局能力}

---

## 六维评分

| 维度 | 分数 | 说明 |
|---|---|---|
| 起手稳定性 consistency | {value}/10 | {reason} |
| 终场上限 ceiling | {value}/10 | {reason} |
| 抗干扰能力 resilience | {value}/10 | {reason} |
| 后攻能力 going_second | {value}/10 | {reason} |
| 资源续航 grind | {value}/10 | {reason} |
| 展开多样性 route_diversity | {value}/10 | {reason} |

---

## 总结

**优势**
{优势列表}

**弱点**
{弱点列表，包含具体卡名和场景}
```

---

## 错误处理

如果某个步骤失败：
1. 停止执行，告知用户哪步失败、失败原因、以及已保存的产物文件路径
2. 用户下次重新触发时，从失败步骤重新开始

**不算失败的情况**：
- Step 1.5 的禁限超限（退出码 `1`）：这是分析结论的一部分，记录后在报告中说明，继续执行
- Step 4.5 的 `[VALIDATION FAILED]`：不是失败，但在修正前不得进入 Step 5
