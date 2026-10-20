---
name: deck-parser
description: 游戏王卡组结构解析 skill。接收 CLI 原始卡片数据（deck_raw.csv），识别 engine、starter、extender、手坑，计算起手概率，输出结构化卡组数据 JSON。只做事实提取，不做对局判断。通常由 ygo-deck-analyze 调用，输入为 deck_raw.csv，输出为 deck_parsed.json。
---

# deck-parser

## 职责边界

这个 skill **只做事实提取**，不做判断。

- ✅ 卡片是什么、效果是什么、分几张
- ✅ 这张卡属于哪个 engine
- ✅ 这张卡是 starter / extender / 手坑 / 终场
- ✅ 起手概率计算
- ❌ 不评价卡组好不好
- ❌ 不分析弱点或对局表现
- ❌ 不给建议

对局分析由 `deck-analyzer` skill 负责。

---

## 输入

读取工作目录中的 `deck_raw.csv`，内容为 `get-cards-by-ydk` CLI 工具的原始返回数据（CSV格式）。

---

## 解析流程

### Step 0 — 脚本事实（必做）

在分类之前，先把「这张卡在规则上到底怎么运作」从脚本里读出来，不要凭中文文本推断：

```bash
python skills/deck-parser/scripts/script_facts.py --ydk {ydk} --cache .cache/ygopro-scripts -o script_facts.json
```

每张卡会得到：

| 字段 | 含义 | 后续用途 |
|---|---|---|
| `opt` | `card_name_once` / `once_per_turn` / `unlimited` / `custom` | 直接作为 `once_per_turn_type` |
| `effects[].kind` | `ignition` / `trigger_optional` / `quick_optional` / … | 区分 starter 与 handtrap |
| `effects[].no_miss_timing` | `true` = 不会错过时点（等价「場合」） | 判断这条线会不会被前置处理挤掉（C2） |
| `effects[].targets` | 是否取对象 | 判断对象抗性挡不挡（C6） |
| `effects[].has_cost` | 这一步是否 cost | 判断能否被灰流丽响应（C5） |
| `restrictions` | 效果里直接声明的自锁 | `self_lock_risk` |
| `indirect_restrictions` | 结算时才挂载的自锁 | 同上 |

规则判据的完整说明见 `ocg-rules` skill。

#### `opt` 为 `custom` 时（必做）

脚本里没有 `SetCountLimit`，次数限制是用 `Duel.GetFlagEffect` 或 `aux.Enable*` 实现的。工具会把证据原样列出：

```json
"custom_evidence": {
  "flag_checks": ["Duel.GetFlagEffect(tp,84192580) <= 1"],
  "aux_helpers": ["EnableMulcharmyGlobalCheck"]
}
```

此时**不得直接归类**，必须：

1. 读证据：flag 里用的是**哪张卡的 id**？如果是别人的 id，说明这是跨卡共享的限制，不是本卡的限制
2. 判定本卡实际的次数限制
3. 在 `deck_parsed.json` 里写 `once_per_turn_type` + `once_per_turn_source: "script_custom"`，并在 `effect_summary` 里写明依据

> 例：欢聚友伴系列用 `GetFlagEffect(tp, 84192580)`（水母的 id）+ `EnableMulcharmyGlobalCheck`，实现的是**整个系列的回合限制**——单看山雀是 `card_name_once`，实际是跨卡互斥。

---

### Step 1 — 卡片分类

读取每张卡的效果文本，将每张卡归入以下类型。一张卡可以归入多个类型。

| 类型 | 定义 |
|---|---|
| `starter` | 能独立启动主引擎展开、或检索到关键卡的卡片。通常是 normal summon 后搜索、或一卡展开的魔法。 |
| `extender` | 无法独立启动展开，但能在 combo 进行中提供额外召唤点或资源的卡片。通常是从手牌/墓地特殊召唤的补点。 |
| `handtrap` | 在对手回合从手牌发动效果来干扰对手的卡片。包括但不限于：从手卡丢弃/送墓发动的怪兽效果、以及满足特定条件可从手卡发动的陷阱卡。 |
| `engine_core` | 属于某个 archetype 的核心卡，但不属于上面三类（例如 combo 中途的素材、终场怪兽的素材来源）。 |
| `endboard` | 在终场留场、持续提供抗性/干扰/效果的卡片。**不限于额外卡组怪兽**，主卡组的效果怪兽、陷阱怪兽、永续魔法/陷阱均适用。判断标准：这张卡在终场是否还在场上发挥持续作用？即使自身没有主动干扰效果，但能通过联动提供保护或触发式干扰的卡片也必须归入此类。 |
| `mid_material` | 主要用作中途 link/xyz/synchro 素材的额外卡组怪兽。 |
| `boardbreaker` | 主要用于突破对手盘面的卡片，例如冥王结界波、拮抗者、坏兽等。 |
| `floodgate` | 持续限制对手行动的永续魔陷或怪兽效果。 |
| `resource_denial` | 通过破坏对手手牌、卡组或墓地资源来压制对手的卡片，例如轰雷帝、暗黑界军神。注意：这类卡通常本身就是某些卡组的终场核心，而非通用工具。 |
| `enabler` | 靠自己的召唤/发动去触发别的卡的效果，本身不产生资源。典型是素材条件宽松的 Link-1：它把「除外状态的卡在连接怪兽特殊召唤时回场」这类需求变成可用的展开起点。 |
| `utility` | 不属于以上类型的泛用功能卡。 |

#### 关于 `endboard` 的多标签说明

`extender` 和 `endboard` 对同一张卡经常同时成立，两个标签不互斥。
典型情况：一张卡在展开中作为补点（extender），但留场后持续提供抗性或干扰效果（endboard）。
**不要因为一张卡是 extender 就排除它成为 endboard 的可能性，必须独立判断它的终场价值。**

#### 关于陷阱怪兽（Trap Monsters）

陷阱怪兽具有双重身份，分类时注意：
- 在手牌/盖放时是**陷阱**，在场上特召后是**怪兽**。

---

### 关于 once_per_turn_type

**取值来自 Step 0 的 `opt`，不要读文本猜。**

| 值 | 定义 |
|---|---|
| `card_name_once` | 卡名限制：同名卡在同一回合只能发动一次。多张同名的意义仅是提高起手率。 |
| `once_per_turn` | 有一回合一次限制，但没有卡名绑定。在特定条件下（不同状态、不同位置）同一张卡可以多次发动，或多张同名可各自发动。 |
| `unlimited` | 没有次数限制，理论上可以在同一回合内多次发动。塞勒涅、神圣魔皇后等靠计数器反复利用的卡属于此类。 |

`deck_parsed.json` 里**只允许这三个值**。脚本给出的 `custom` 必须先人工复核、改写成三态之一，并标注来源：

| `once_per_turn_source` | 何时使用 |
|---|---|
| `script` | 直接取自脚本的 `SetCountLimit`（默认） |
| `script_custom` | 脚本用 flag/aux 计数，经人工复核后判定 |

`once_per_turn` 和 `unlimited` 的卡在资源堆叠上有特殊价值，deck-analyzer 会用这个信息分析资源上限。

---

### Step 2 — Engine 识别

将属于同一 archetype 或同一功能模块的卡片归组，形成 engine 列表。

Engine 归组按以下优先级判断，**高优先级规则命中时，即使 archetype 字段指向其他分组，也以高优先级规则为准**：

**⑤ 召唤/发动条件依赖**（最高优先级）
如果卡片 A 的召唤条件或效果发动条件中，要求场上/墓地存在某张具名卡 B 或某个 archetype 的卡片，则 A 与 B / 该 archetype 存在强依赖，归入同一 engine。
典型特征：
- "自己场上有「X」存在的场合才能特殊召唤"
- "自己场上有「X」archetype 的卡存在时才能发动"

即使 A 有独立的 archetype 字段，也应优先按依赖关系归组。

**② 效果文本卡名直接引用**（高优先级）
如果卡片 A 的效果文本中出现了卡片 B 的完整卡名（通常以「」括起），则 A 与 B 关联，归入同一 engine。即使 A 没有任何 archetype 字段也适用。

**③ 效果文本 Archetype 名引用**（中优先级）
如果卡片 A 的效果文本中出现了某个 archetype 名称，且卡组中存在该 archetype 的卡片 B，则 A 与 B 关联，归入同一 engine。

**④ 功能性产出依赖**（中优先级）
如果一张场地/永续魔法/永续陷阱的效果能直接产出（搜索/特召/盖放）某个 archetype 的卡片，则该卡与该 archetype 归为同一 engine，不论自身 archetype 字段是否为空。

**① Archetype 字段匹配**（兜底）
archetype 字段相同的卡归入同一 engine。这是最弱的归组依据，当上方任一规则命中时，以上方规则为准。

对每个 engine 记录：
- 包含哪些卡片（含通过文本关联加入的）
- 在卡组中的角色（主引擎 / 副引擎 / 独立 package）
- 是否依赖 Normal Summon 启动
- 是否与其他 engine 争抢资源（例如同一额外怪物区位置、同一召唤权）

---

### Step 2.5 — 需求 → 满足者扫描（找二卡动点）

**这一步不能只靠读卡，必须借助脚本。** 40 张主卡组有 780 对组合，人工逐对检查一定会漏。

```bash
python scripts/combo_scan.py deck_raw.json -o combo_candidates.json
```

脚本输出三类信息，**都只是候选，不是结论**：

1. **额外卡组连接怪兽的素材门槛**：每只 Link 的素材条件，以及主卡组里有多少张卡能满足它。
   便宜的 Link-1 往往就是整个卡组的隐藏启动点。
2. **触发需求**：每张卡文本里的「融合·连接怪兽特殊召唤的场合」「被除外的场合」等外部条件。
3. **候选组合**：某张卡的需求 × 能满足它的卡。

随后逐条判断，只有满足下面**全部**条件才算二卡动点：

- 两张牌都能从手牌正常使用（不是必须已在场、不是必须对方配合）；
- 中间每一步都不缺少必要素材（召唤权、格子、支付成本）；
- 走完之后确实产出有效场面（至少一次有意义的连接/融合/同调/超量召唤），而不是「两只怪站着」；
- 不依赖起手 5 张之外的资源。

**判断完成后必须回填 `combo_starters`，并说明用到了哪些 enabler。** 不要因为「主引擎不是它」就跳过——双轴卡组里，副轴的二卡动点经常占总启动率的 10% 以上。

---

### Step 3 — 起手概率计算

**（1）单组概率**：统计 starter 总张数和手坑总张数，调用 `starter-probability`。

```bash
python ../starter-probability/scripts/starter_probability.py -d 40 -t 11
```

**（2）组合概率**：二卡动点用 `--also-count` 算「至少各摸到 1 张」。两组必须互不重叠。

```bash
python ../starter-probability/scripts/starter_probability.py -d 40 -t 4 -a 17
```

**（3）真实起手分布**：这是**唯一能回答「这套牌到底多大比例能动」的办法**。
把 1 卡动点、二卡动点写成规则文件，穷举全部 5 张起手。

```bash
python scripts/hand_matrix.py deck_raw.json combos.json
```

规则文件格式：

```json
{
  "one_card": [
    { "label": "白兔单卡", "cards": ["码丽丝<兵卒>白兔"] }
  ],
  "two_card": [
    { "label": "无限/净化 + Link-1 身体",
      "first": ["无限与有限之无垢大艺术", "净化与腐败之无垢大艺术"],
      "second_predicate": "link1_material" }
  ]
}
```

可用谓词：`link1_material`（手里有能当某只 Link-1 素材的怪）、`link2_material`、`ns_body`（手里有可通召的怪）。
规则里的卡名必须来自主卡组；额外卡组怪兽用谓词表达，不能直接写名字。

**（4）死手率自检**：脚本默认在死手率超过 15% 时告警。**看到告警不要直接写报告**——
对一线卡组来说，>15% 通常意味着还有没识别的二卡动点，先回 Step 2.5 复查。加 `--strict` 可让它直接以失败结束。

---

## 输出格式

输出合法 JSON，dump 到 `deck_parsed.json`。

```json
{
  // 卡组基本信息
  "deck_profile": {
    "archetype": "卡组主题名称，例如 '蛇眼' / '白噪音'",
    "deck_type": "卡组风格，枚举值：'combo' | 'control' | 'midrange' | 'turbo'",
    "difficulty": "操作难度，枚举值：'low' | 'medium' | 'high'"
  },

  // 卡组规模，来自 count-deck
  "deck_structure": {
    "main": 0,   // 主卡组张数
    "extra": 0,  // 额外卡组张数
    "side": 0    // 副卡组张数
  },

  // Engine 列表，每个 engine 一个对象
  "engines": [
    {
      "name": "engine 名称，例如 '蛇眼引擎'",
      "role": "primary | secondary | package  // primary=主引擎, secondary=副引擎, package=独立功能包",
      "cards": [
        {
          "name": "卡片名称",
          "copies": 0,
          "types": [],        // 此卡的类型列表，从上方类型枚举中选取，endboard 和 extender 可同时存在
          "once_per_turn_type": "card_name_once | once_per_turn | unlimited",
          "join_reason": "archetype字段匹配 | 效果引用「X」| archetype名引用「X」| 功能性产出「X」| 召唤/发动条件依赖「X」  // 说明这张卡为何归入本 engine，archetype字段匹配时可省略",
          "endboard_role": "这张卡在终场的持续贡献，例如'为全场陷阱怪兽提供对象抗性；被破坏时触发联动'。仅在 types 含 endboard 时填写，否则填 null",
          "effect_summary": "一句话说明效果或在 engine 中的作用"
        }
      ],
      "normal_summon_dependent": true,
      "resource_conflicts": "与哪个 engine 存在资源冲突，没有则填 null"
    }
  ],

  // 二卡动点（combo starter）汇总
  // 一张卡自己动不了、但配另一张就能动。必须写清前提、enabler 与整条线路。
  "combo_starters": [
    {
      "label": "无限/净化 + Link-1 身体",
      "cards": ["无限与有限之无垢大艺术", "净化与腐败之无垢大艺术"],
      "requires": "任意可通常召唤、且满足 Link-1 素材条件的怪兽",
      "enablers": ["转生炎兽 独角兔", "连环栗仔球"],
      "requires_normal_summon": true,
      "line_summary": "无限①除外自身检索净化 → 净化①检索黄昏 → 黄昏②检索结合 → 结合①从除外区拉回无限 → NS 怪做 Link-1 → 净化②/结合②回场 → I:P → 小男巫 → 防火龙",
      "verified": true
    }
  ],

  // Starter 汇总（只放「单卡就能启动」的）
  "starters": {
    "cards": [
      {
        "name": "卡片名称",
        "copies": 0,
        "once_per_turn_type": "card_name_once | once_per_turn | unlimited",
        "effect_summary": "一句话说明这张卡如何启动展开"
      }
    ],
    "total_copies": 0
  },

  // Extender 汇总
  "extenders": {
    "cards": [
      {
        "name": "卡片名称",
        "copies": 0,
        "once_per_turn_type": "card_name_once | once_per_turn | unlimited",
        "effect_summary": "一句话说明这张卡如何补充展开"
      }
    ],
    "total_copies": 0
  },

  // 手坑汇总
  "handtraps": {
    "cards": [
      {
        "name": "卡片名称",
        "copies": 0,
        "once_per_turn_type": "card_name_once | once_per_turn | unlimited",
        "effect_summary": "一句话说明效果"
      }
    ],
    "total_copies": 0
  },

  // Boardbreaker 和封锁卡汇总（非手坑类，用于突破对手盘面或限制对手行动）
  "boardbreakers_and_floodgates": {
    "cards": [
      {
        "name": "卡片名称",
        "copies": 0,
        "type": "boardbreaker | floodgate | resource_denial",
        "once_per_turn_type": "card_name_once | once_per_turn | unlimited",
        "effect_summary": "一句话说明效果"
      }
    ]
  },

  // 额外卡组怪兽列表
  "extradeck_monsters": [
    {
      "name": "卡片名称",
      "copies": 0,
      "role": "endboard | mid_material | both  // 终场 / 中途素材 / 两者皆是",
      "effect_summary": "一句话说明在 combo 中的作用"
    }
  ],

  // 主卡组终场核心列表
  // 主卡组中 types 含 endboard 的卡片，在此单独汇总，便于 deck-analyzer 直接定位
  "maindeck_endboard": [
    {
      "name": "卡片名称",
      "copies": 0,
      "card_type": "effect_monster | trap_monster | continuous_spell | continuous_trap | field_spell | other",
      "once_per_turn_type": "card_name_once | once_per_turn | unlimited",
      "endboard_role": "这张卡在终场的持续贡献",
      "effect_summary": "一句话说明效果"
    }
  ],

  // 起手概率，来自 starter-probability，直接保留 tool 原始输出的完整分布
  "probability": {
    "starter": {
      "total_copies": 0,        // starter 总张数，即 tool 的 target_count
      "exactly_1": "0.00%",     // 刚好摸到 1 张的概率，来自 tool 输出的 probabilities.1
      "exactly_2": "0.00%",     // 刚好摸到 2 张的概率，来自 tool 输出的 probabilities.2
      "at_least_1": "0.00%",    // 至少摸到 1 张的概率，来自 tool 输出的 at_least_1
      "at_least_2": "0.00%"     // 至少摸到 2 张的概率，来自 tool 输出的 at_least_2
    },
    "handtrap": {
      "total_copies": 0,
      "exactly_1": "0.00%",
      "exactly_2": "0.00%",
      "at_least_1": "0.00%",
      "at_least_2": "0.00%"
    },
    // 二卡动点组合概率，来自 starter-probability 的 --also-count
    "two_card": {
      "group_a_copies": 0,
      "group_b_copies": 0,
      "both": "0.00%",          // 同时摸到 A 与 B
      "either": "0.00%"         // 至少摸到 A 或 B
    }
  },

  // 穷举起手手牌的结果，来自 hand_matrix.py（这是「能动率」的唯一可靠来源）
  "hand_matrix": {
    "hand_size": 5,
    "total_hands": 0,
    "one_card_rate": "0.00%",
    "two_card_rate": "0.00%",
    "startable_rate": "0.00%",
    "dead_rate": "0.00%",
    "dead_over_threshold": false,
    "by_label": {
      "规则标签": "0.00%"
    }
  }
}
```
