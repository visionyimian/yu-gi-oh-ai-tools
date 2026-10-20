# Yu-Gi-Oh! AI Tools - Skills

A collection of AI skills for analyzing Yu-Gi-Oh! decks using Claude Code.

## Currently Available Skills

### Core Analysis Skills

| Skill | Description |
|-------|-------------|
| **ygo-deck-analyze** | Main orchestrator that coordinates the complete deck analysis pipeline. Accepts `.ydk` files and generates human-readable reports. |
| **deck-parser** | Parses raw card data to identify engines, starters, extenders, hand traps, and calculates opening probabilities. Performs fact extraction only, no gameplay judgment. |
| **deck-analyzer** | Performs comprehensive gameplay analysis including combo diversity, first-turn endboard quality, weaknesses, handtrap sensitivity, chokepoints, going-second capability, and resource sustainability. Outputs 6-dimensional scores. |

### Utility Skills

| Skill | Description |
|-------|-------------|
| **starter-probability** | Calculates the probability of drawing specific cards (starters, hand traps) in a 5-card starting hand using hypergeometric distribution. |
| **count-deck** | Counts cards in main deck, extra deck, and side deck from a YDK file. |
| **ocg-banlist** | Fetches the YGOCore limit list (`lflist.conf`) for OCG or TCG and validates a `.ydk` against it. |
| **simple-calculator** | Basic arithmetic calculations (+, -, *, /). |

## Analysis Pipeline

The `ygo-deck-analyze` skill orchestrates a 4-step process:

```
.ydk file
    ↓
Step 1.5: Banlist check → banlist_check.txt          (ocg-banlist)
    ↓
Step 2: Get raw card data → deck_raw.csv / deck_raw.json
    ↓
Step 3: Parse deck structure → deck_parsed.json
        + combo_scan.py   找出「需求 → 满足者」候选（二卡动点）
        + hand_matrix.py  穷举 5 张手牌，得到真实的能动率 / 死手率
    ↓
Step 4: Gameplay analysis → deck_analysis.json
    ↓
Step 4.5: Consistency validation (endboard coverage, hand_matrix)
    ↓
Step 5: Generate report → report.md
```

> 二卡动点（combo starter）不能靠读卡发现。`combo_scan.py` 扫描每张卡的
> 外部需求（例如「融合·连接怪兽特殊召唤的场合」）并去卡组里找满足者，
> `hand_matrix.py` 再把确认过的动点规则穷举成百分比。死手率超过 15% 会触发告警，
> 提示回去复查是否漏了启动点。

## Output Format

Each analysis generates:
- `banlist_check.txt` - Legality check against the OCG/TCG limit list, plus the list version used
- `deck_raw.json` - Raw card data
- `deck_parsed.json` - Structured deck information (engines, starters, extenders, hand traps)
- `deck_analysis.json` - Comprehensive gameplay analysis with 6-dimensional scoring
- `report.md` - Human-readable analysis report

## Todo List

### 1. Add English (TCG) Version of Skills

The current skills are primarily in Chinese. Need to:

- [ ] Translate skill descriptions and prompts from Chinese to English
- [ ] Ensure TCG terminology is used correctly (e.g., "hand trap" vs "手坑", "starter" vs "展开点", "board breaker" vs "解场卡")
- [ ] Update reason field templates to use TCG-standard card names and terms

Note: TCG database support is already covered by existing ygo-db-cli tools.

### 2. Meta-Analyzer Skill

Create a new skill to analyze the competitive meta:

- [ ] Download meta deck lists from online sources (Master Duel, YGOProDeck, etc.)
- [ ] Calculate meta share statistics by archetype
- [ ] Identify common tech cards and hand trap ratios
- [ ] Track card usage trends over time
- [ ] Generate meta reports with deck archetype breakdown

### 3. Combo-Analyzer Skill (Long-term)

An advanced skill using ygopro-core to simulate combos:

- [ ] Integrate ygopro-core Lua engine
- [ ] Build combo tree/graph from deck lists
- [ ] Identify optimal lines and chokepoints
- [ ] Calculate turn 1 board probabilities
- [ ] Find alternative routes when interrupted
- [ ] Generate visual combo maps

## Notes

- All analysis skills are designed for OCG format by default
- The `deck-analyzer` skill requires `resources/handtraps.csv` and `resources/boardbreakers.csv` for complete analysis
- Each judgment in the analysis includes a `reason` field to support reproducible analysis

## License

Part of the yu-gi-oh-ai-tools project.
