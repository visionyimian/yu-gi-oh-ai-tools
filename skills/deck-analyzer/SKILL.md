---
name: deck-analyzer
description: 游戏王卡组对局分析 skill。接收 deck_raw.csv 和 deck_parsed.json，对卡组进行系统化对局分析，输出带完整 reasoning 的分析 JSON。分析维度包括：展开多样性、先攻终场质量与弱点、系统性弱点、手坑敏感度、Chokepoint、后攻突破力、资源续航、六维评分。每个判断必须附带 reason。通常由 ygo-deck-analyze 调用，输出为 deck_analysis.json。
---

# deck-analyzer

## 职责边界

这个 skill **只做分析和判断**，不调用任何工具。

- ✅ 接收 `deck_raw.csv` 和 `deck_parsed.json` 作为输入
- ✅ 读取 `resources/handtraps.csv` 和 `resources/boardbreakers.csv` 作为分析基准
- ✅ 对卡组进行多维度对局分析
- ✅ 每个判断都必须附带 `reason`，说明依据
- ✅ 输出六维评分（对照锚点标准）
- ❌ 不调用任何工具
- ❌ 不假设卡片效果（所有卡片信息来自输入文件）

> **关键原则**：所有判断必须有 reason。reason 是这个 skill 的核心价值——让后续读取 JSON 的 agent 在转述时有依据，而不是重新推理或胡诌。

---

## 输入

- `deck_raw.csv`：CLI 原始卡片数据（CSV格式）
- `deck_parsed.json`：deck-parser 的结构化输出
  - `combo_starters`：二卡动点（一张卡动不了、配另一张就能动）
  - `hand_matrix`：穷举 5 张手牌得到的真实起手分布
- `resources/handtraps.csv`：当前 meta 手坑列表，含效果摘要和分析重点
- `resources/boardbreakers.csv`：当前 meta 解场卡列表，含效果摘要和分析重点

> 如果 CSV 文件不存在，跳过对应部分并在输出中注明 `"resources_missing": true`，继续完成其他分析维度。

---

## Step 0 — 输入完整性自检（不通过就不要往下写）

1. **死手率**：如果 `hand_matrix.dead_rate` > 15%，这通常不是「卡组缺陷」而是「解析漏了二卡动点」。
   回到 `combo_scan` 的候选表复查「需求 → 满足者」，补完 `combo_starters` 后重跑 `hand_matrix`。
2. **enabler 检查**：卡组里只要存在「这张卡是除外状态，连接/融合怪兽特殊召唤的场合才能发动」这类效果，
   就必须确认 `combo_starters` 里至少考虑过「最便宜的那次连接召唤」是不是启动点。
3. **额外卡组的 Link-1**：素材条件宽松的 Link-1（通常召唤的攻击力 N 以下 / N 星以下某种族）
   经常是隐藏启动点，不能在 `extradeck_monsters` 里只标成 `mid_material` 就算完。

---

## 分析流程

### Step 1 — 展开多样性

目标：分析卡组**内生的路线结构**，即卡组本身有多少条独立的展开路线，这些路线之间的重叠程度有多高。

这不是分析"怕什么手坑"（那是 Step 5 的工作），而是分析"卡组结构本身有多宽"。

**1a. 起手宽度**

统计有多少张不同的 starter 能**独立**启动展开（不依赖其他特定手牌配合）。

- 独立 starter 越多，起手宽度越高
- 若多张 starter 走的是同一条路线，宽度不增加，只增加稳定性

**1b. 展开中段分叉**

分析展开中途是否存在分叉点：

- 某张关键卡缺席时，能否走另一条路到达相同或接近的终场？
- 还是所有路线都经过同一个必经节点（单点死亡）？

识别必经节点：如果任何一条展开路线都必须经过某张卡或某个步骤，该节点就是单点，路线多样性低。

**1c. 终场可达性**

分析残局展开的终场质量：

- 少一张 extender，终场妨碍数量从几变几？
- 完整展开和残局展开的终场差距有多大？
- 卡组是否有多个"档位"的终场（3妨碍 / 2妨碍 / 1妨碍），还是非全即零？

**1d. 综合判断**

- `multi_route`：有多条独立路线，中段有分叉，残局仍能建出有效终场
- `single_route`：路线单一，存在明显单点，残局终场质量大幅下降

---

### Step 2 — 先攻终场分析

#### 先想清楚「场值」这个账

做场不是「能不能做出某只额外卡组怪兽」，而是**把场上的场值做到最大、再决定怎么花**。

| 概念 | 定义 |
|---|---|
| **场值** | 每个非连接怪兽算 1；连接怪兽算它的连接标记数（Link-4 = 4 场值） |
| **打包** | 连接召唤不产生场值，只是把 N 个场值换成一个额外卡组格子 |
| **净增** | 来源是「被除外 → 自我特召」这类效果（每次 +1），以及用少于标记数的素材做连接怪兽 |
| **花掉** | 用高标记的连接怪兽当低标记的素材，差额就是花掉的场值——换来的是那只怪兽的效果 |

场值**不是只能涨**。典型例子：Link-3 的「白棋捆绑」加 1 只怪共 4 场值，做出来的「电子界小男巫」只有 Link-2，差额 2 点是花掉的，买的是小男巫的检索。写 `steps` 时用 `spend` 记这笔支出，用 `gain` 记净增；任何一步场值变了都必须解释。

**每一步还要能被机器认出来。** 除了自然语言的 `act`，加上两个结构化字段：

- `action`：这一步是什么动作（`normal_summon` / `special_summon` / `link_summon` / `activate` / `resolve`）
- `uses`：这一步消耗了哪些效果，写成 `[{ "card": "卡名", "effect": "①" }]`

有了 `uses`，模拟器才知道该去引擎给的选项里找哪一个；没有它，24 步就只是散文。
一步里可以引用多个效果（例如「毒蜥① 除外睡鼠 → 睡鼠③ 回场」是两处引用），
而「同一个效果在后续步骤里结算」不算新的引用，用 `action: "resolve"` 标出来。

**循环是有上限的。** 碰到「陷阱把连接怪兽当 cost 除外 → 连接怪兽③ 自跳回场」这类结构时，先找它的天花板：只要这些卡都是「卡名 1 回合 1 次」，循环次数就等于**不同名卡的数量**，不是无限的。码丽丝里是 TB-11 / MTP-07 / GWC-06 三张，所以一轮最多转三次。写 `notes` 时把上限写清楚，别让读者以为可以一直滚。

写 `combo_lines` 时逐步记 `field_value`，就能一眼看出这条线到底涨了几点、哪一步是白赚、哪一步只是打包。

你需要根据`maindeck_endboard`和`extradeck_monsters`分析可能的先攻终场。

**终场类型判断**：
- `NEGATE_BOARD`：以多重效果无效为主
- `FLOODGATE_BOARD`：以规则限制（锁特召、锁属性等）为主
- `TOWER_BOARD`：以高抗性、难以去除的怪兽为主
- `RESOURCE_DENIAL_BOARD`：主动破坏对手手牌、卡组或墓地资源，让对手下回合无法运作。轰雷帝、暗黑界军神等属于此类终场的核心。这类终场的威胁不在于"拦对手的动作"，而在于"让对手没有动作可做"。
- `MIXED_BOARD`：以上类型混合

**阻抗结构**：统计前场阻抗（怪兽效果）和后场阻抗（魔陷）的数量和类型。

**抗性分析**：判断是否有效果对象抗性、破坏抗性、战斗抗性，以及来源是永续还是一次性。

**终场完整度**：
- 是否需要"所有牌都到位"才能建成完整终场
- 部分资源是否能建成次级终场
- 建完终场后是否仍有手牌资源
- 终场怪兽是否有攻击能力（拦完能反击吗）
- 是否存在自锁风险

---

### Step 3 — 终场弱点矩阵

分析对手用哪些**盘面突破手段**能打穿我的终场。

以 `resources/boardbreakers.csv` 中的解场卡为分析基准，逐一评估每张解场卡对该终场的有效程度：
- `highly_effective`：能直接突破终场
- `partially_effective`：能削弱但不能完全突破
- `ineffective`：终场能抵御

每条记录必须附 `reason`，说明依据（例如"终场怪兽有破坏抗性，坏兽无效；但无对象抗性，禁忌的一滴有效"）。

---

### Step 4 — 系统性弱点分析

目标：找出卡组在**机制层面**的脆弱性。

与终场弱点不同：终场弱点是"对手怎么打穿我建好的盘面"，系统性弱点是"对手怎么让我根本建不起来"。

对每个核心机制依赖，分析：
- **依赖什么**：墓地 / 特召 / 检索加手 / 特定卡名联动 / 魔法 / 额外卡组
- **被针对后能做什么**：完全停摆 / 大幅削弱但还能运作 / 有替代路线
- **meta 出现频率**：`common` / `uncommon`

---

### Step 5 — 手坑敏感度分析

以 `resources/handtraps.csv` 中的手坑为分析基准，对每张手坑找出展开中最容易被打断的具体节点。

**增殖的G这类如果你展开会抽卡 需要特殊处理**：

G 不打断展开，而是制造"继续展开=给对手抽牌"的困境。分析重点是：
- 面对 G，最优停手点在哪一步？
- 停下来时场面有什么，能拦几次？
- 如果强行展完，对手大约能抽几张？
- 卡组的正确应对是停手还是展完？

对其余每张手坑记录：
- `impact`：`critical` / `significant` / `minor` / `negligible`
- `timing`：被打断的具体时机（要具体到哪张卡发动什么效果时）
- `reason`：为什么这个时机关键
- `has_counter`：卡组是否有应对手段
- `counter_card`：应对手段卡名，没有填 null

---

### Step 6 — Chokepoint 分析

识别展开路线中的关键节点，一旦被打断会导致展开严重受损。

对每个 chokepoint 记录：
- 展开步骤描述（第几步、什么动作）
- 涉及的卡片
- 为什么是关键节点
- 哪些手坑能在此处打断
- 是否有绕过的替代路线

---

### Step 7 — 后攻突破能力

评估：
- 专用解场卡有哪些，各自的功能
- 突破效率：一换多还是一换一
- 突破后余力：清场后还有多少资源
- OTK 潜力

---

### Step 8 — 资源续航

评估：
- 持续检索机制
- 墓地资源循环
- `once_per_turn` 和 `unlimited` 类卡片的资源堆叠上限（来自 `deck_parsed.json` 的 `once_per_turn_type` 字段）——例如塞勒涅、神圣魔皇后这类可以在同一回合多次发动的卡，是否被利用来堆资源
- 第 3 回合的资源状况
- 是否是一锤子买卖型卡组

---

## 评分标准

六个维度，每个维度 1–10 分，对照锚点打分，必须附 reason。

### consistency（起手稳定性）

**以 `deck_parsed.json` 的 `hand_matrix.startable_rate`（穷举 5 张手牌后「能动」的比例）为准**，
不要用单卡 starter 张数代替——二卡动点同样算数，而且经常占 10% 以上。

| 分数 | 锚点条件 |
|---|---|
| 9–10 | 能动率 ≥ 88% |
| 7–8 | 能动率 78–87% |
| 5–6 | 能动率 65–77% |
| 3–4 | 能动率 50–64% |
| 1–2 | 能动率 < 50% |

`reason` 里必须写出这个百分比，并说明它是穷举得到的（`hand_matrix`），不是估算的；
同时写出 `dead_rate`，以及死手主要是哪些牌。

### ceiling（终场上限）

| 分数 | 锚点条件 |
|---|---|
| 9–10 | 终场有 4+ 妨碍，包含多重无效 + 抗性怪，对手极难突破 |
| 7–8 | 终场有 3 妨碍，或 2 妨碍但包含高质量锁定效果 |
| 5–6 | 终场有 2 妨碍，或妨碍质量参差不齐 |
| 3–4 | 终场只有 1 妨碍，或终场容易被单张卡突破 |
| 1–2 | 基本没有终场，主要靠战斗伤害取胜 |

### resilience（抗干扰能力）

| 分数 | 锚点条件 |
|---|---|
| 9–10 | 多个 chokepoint 都有替代路线，能对抗多种手坑 |
| 7–8 | 主要 chokepoint 有替代路线，只怕 1–2 种特定手坑 |
| 5–6 | 有 1–2 条替代路线，但被常见手坑打到会明显受损 |
| 3–4 | 展开路线单一，被灰流丽或无限泡影打到就大幅削弱 |
| 1–2 | 几乎没有替代路线，单张手坑就能完全断掉展开 |

### going_second（后攻能力）

| 分数 | 锚点条件 |
|---|---|
| 9–10 | 有专用解场套件 + 突破后能建立自己的强终场 + 有 OTK 潜力 |
| 7–8 | 能有效突破主流终场，突破后仍有资源展开 |
| 5–6 | 能突破但效率一般，或突破后资源耗尽 |
| 3–4 | 突破手段稀少，主要依赖卡组本身战斗力 |
| 1–2 | 几乎没有专用后攻手段，先攻依赖型卡组 |

### grind（资源续航）

| 分数 | 锚点条件 |
|---|---|
| 9–10 | 每回合稳定补充手牌 + 墓地资源循环 + 长局优势明显 |
| 7–8 | 有检索机制，2–3 回合内不会断粮 |
| 5–6 | 资源一般，打长局会逐渐处于下风 |
| 3–4 | 资源薄弱，先攻失败后很难翻盘 |
| 1–2 | 一锤子买卖，先攻没关闭游戏基本输 |

### route_diversity（展开多样性）

| 分数 | 锚点条件 |
|---|---|
| 9–10 | 多张独立 starter 走不同路线，中段有分叉，残局仍能建出 3+ 妨碍 |
| 7–8 | 有 2–3 条独立路线，残局能建出 2 妨碍 |
| 5–6 | 路线基本独立但中段有单点，残局终场明显缩水 |
| 3–4 | 路线单一，所有 starter 走同一条路，单点明显 |
| 1–2 | 完全单线，缺任意关键卡就无法建出有效终场 |

---

## 输出格式

输出合法 JSON，dump 到 `deck_analysis.json`。所有判断字段必须附带 `reason`。

```json
{
  // 是否成功读取 CSV 资源文件
  "resources_loaded": {
    "handtraps_csv": true,
    "boardbreakers_csv": true
  },

  // ===== 展开多样性 =====
  "route_diversity": {
    "starter_width": {
      "independent_starter_count": 0,  // 能独立启动展开的 starter 种数
      "routes_are_distinct": true,     // 这些 starter 走的路线是否不同
      "reason": "说明各 starter 走的是什么路线，是否有重叠"
    },
    "mid_combo_branching": {
      "has_single_point_of_failure": false,
      "single_point_card": "单点卡名，没有则填 null",
      "branch_points": ["分叉点描述，例如 '第二步可选择走 A 路或 B 路'"],
      "reason": "说明中段结构"
    },
    "endboard_accessibility": {
      "full_combo_interactions": 0,    // 完整展开的妨碍数
      "partial_combo_interactions": 0, // 少一张 extender 时的妨碍数
      "has_tiered_endboard": false,    // 是否有多个档位的终场
      "reason": "说明完整和残局终场的差距"
    },
    "overall_verdict": "multi_route | single_route",
    "overall_reason": "综合判断说明"
  },

  // ===== 先攻终场 =====
  "first_turn_board": {
    "board_type": "NEGATE_BOARD | FLOODGATE_BOARD | TOWER_BOARD | RESOURCE_DENIAL_BOARD | MIXED_BOARD",
    "typical_endboard": [
      {
        "card_name": "终场怪兽或魔陷名称",
        "role": "这张卡在终场中的作用"
      }
    ],
    "interaction_count": 0,
    "interaction_profile": {
      "monster_negate_count": 0,
      "spell_trap_negate_count": 0,
      "resistances": {
        "targeting": false,
        "destruction": false,
        "battle": false,
        "source": "persistent | once-per-turn | one-time"
      },
      "lock_effects": [
        {
          "effect": "锁定效果描述",
          "source_card": "来源卡片名称"
        }
      ]
    },
    "board_completeness": {
      "requires_full_combo": true,
      "partial_board_possible": true,
      "has_followup_resources": true,
      "can_attack": true,
      "self_lock_risk": "描述自锁风险，没有则填 null"
    }
  },

  // ===== 终场弱点矩阵 =====
  // 基于 boardbreakers.csv，分析对手如何打穿我建好的盘面
  "endboard_vulnerability": {
    "board_breaker_threats": [
      {
        "threat": "解场卡名称，来自 boardbreakers.csv",
        "effectiveness": "highly_effective | partially_effective | ineffective",
        "reason": "说明为什么有效或无效，结合终场的具体抗性和阻抗结构"
      }
    ],
    "biggest_threat": "对终场威胁最大的解场手段",
    "biggest_threat_reason": "为什么"
  },

  // ===== 系统性弱点 =====
  // 分析对手如何让我根本建不起来，与终场弱点维度不同
  "systemic_vulnerabilities": [
    {
      "dependency": "卡组依赖的核心机制，例如 '高度依赖墓地启动'",
      "critical_cards_at_risk": ["依赖此机制的关键卡名"],
      "lock_type": "墓地封锁 | 检索封锁 | 特召封锁 | 额外卡组封锁 | 特定机制封锁",
      "impact_if_countered": "被针对后的具体影响",
      "meta_prevalence": "common | uncommon | rare"
    }
  ],

  // ===== 手坑敏感度 =====
  // 基于 handtraps.csv
  "handtrap_vulnerability": {
    "analysis": [
      {
        "handtrap": "手坑名称，来自 handtraps.csv",
        "impact": "critical | significant | minor | negligible",
        "timing": "被打断的具体时机，要具体到哪张卡发动什么效果时",
        "reason": "为什么这个时机关键",
        "has_counter": false,
        "counter_card": "应对手段卡名，没有填 null"
      }
    ]
  },

  // ===== Chokepoint =====
  "chokepoints": [
    {
      "step": "展开步骤描述，例如 '第一步：Normal Summon 蛇眼炎龙'",
      "card_involved": "涉及的卡片名称",
      "why_critical": "为什么这个节点是整个展开的关键",
      "vulnerable_to": ["手坑名称"],
      "has_alternate_route": false,
      "alternate_route_description": "替代路线描述，没有填 null"
    }
  ],

  // ===== 做场步骤 =====
  // 报告里「怎么做出来」的唯一来源。核心是**场值账本**，不是「能不能做出某只怪」。
  //
  // 场值模型：
  //   - 每个非连接怪兽 = 场值 1；连接怪兽 = 它的连接标记数
  //   - 连接召唤**不产生场值**，只是把 N 个场值打包进一个额外卡组格子
  //   - 唯一净增来源是「被除外 → 自我特召」这类效果，每触发一次 +1
  //   - 所以「把每只的效果都发一遍」= 让每只的①各制造一次③的机会
  "combo_lines": [
    {
      "name": "白兔线：3 场值 → 4 场值",
      "goal": "把 1 张起手做成 4 场值终场",
      "starter": "起手卡名，必须是 combos.json 里识别过的动点",
      "hand_required": ["这条线最少需要摸到的卡"],
      "cards_used": ["整条线用到的卡，用来校验这些卡真的在卡组里"],
      "steps": [
        { "act": "NS 白兔", "field_value": 1, "gain": null, "spend": null,
          "action": "normal_summon",
          "uses": [],
          "note": "gain 写净增，spend 写花掉——场值不是只能涨" },
        { "act": "TB-11 除外白兔，从卡组拉睡鼠", "field_value": 1, "gain": null, "spend": null,
          "action": "activate",
          "uses": [{ "card": "码丽丝<代码>TB-11", "effect": "①" }],
          "note": "白兔离场、睡鼠上场，总数不变" },
        { "act": "白兔③ 支付 300 回场", "field_value": 2, "gain": "+1（③ 回场）", "spend": null,
          "action": "special_summon",
          "uses": [{ "card": "码丽丝<兵卒>白兔", "effect": "③" }] }
      ],
      "peak_field_value": 4,
      "endboard_options": [
        { "name": "A. 留场不动", "board": ["场上还留什么"], "cost": "花掉几场值",
          "interactions": 1, "pros": "优点", "cons": "代价" }
      ],
      "choice_reason": "从这些选项里为什么选这个终场",
      "endboard": ["最终选择"],
      "interactions": 3,
      "branches": [
        { "if": "白棋捆绑被无限泡影", "then": "停在哪、怎么保住资源" }
      ],
      "notes": "风险、吃不吃通召、被什么打断",
      "verdict": "推荐 | 备选 | 不推荐",
      "verified": false,
      "starter_note": "只有当起手不在 combos.json 里时才写：为什么推导器漏了它"
    }
  ],

  // ===== 后攻能力 =====
  "going_second": {
    "board_breaking_tools": [
      {
        "card": "解场卡名称",
        "function": "这张卡如何帮助突破"
      }
    ],
    "breaking_efficiency": "one_for_many | one_for_one | inefficient",
    "post_break_followup": "描述突破后还能做什么",
    "otk_potential": "描述 OTK 潜力，没有则填 null"
  },

  // ===== 资源续航 =====
  "grind_game": {
    "search_engine": "描述持续检索机制，没有则填 null",
    "graveyard_loop": "描述墓地资源循环机制，没有则填 null",
    "unlimited_effect_exploitation": "描述 once_per_turn / unlimited 类卡片的资源堆叠利用，没有则填 null",
    "turn3_viability": "描述第3回合的资源状况",
    "is_one_shot": false
  },

  // ===== 优劣势总结 =====
  "strengths": [
    "优势描述，要具体，例如 '有三条独立展开路线，灰流丽只能打断其中一条'"
  ],
  "weaknesses": [
    "弱点描述，要具体，包含卡名和场景，例如 '高度依赖墓地，次元吸引者一卡让整套combo无法启动'"
  ],

  // ===== 六维评分 =====
  "score": {
    "consistency": {
      "value": 0,
      "reason": "对照评分锚点的打分说明，引用具体数据，例如 'starter 开出率 82%，对应 7–8 分锚点'"
    },
    "ceiling": {
      "value": 0,
      "reason": "对照评分锚点的打分说明"
    },
    "resilience": {
      "value": 0,
      "reason": "对照评分锚点的打分说明"
    },
    "going_second": {
      "value": 0,
      "reason": "对照评分锚点的打分说明"
    },
    "grind": {
      "value": 0,
      "reason": "对照评分锚点的打分说明"
    },
    "route_diversity": {
      "value": 0,
      "reason": "对照评分锚点的打分说明，例如 '有3条独立路线，中段有分叉，残局能建2妨碍，对应7–8分'"
    }
  }
}
```
