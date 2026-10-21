---
name: combo-analyzer
description: Builds and audits a deck's combo model as machine-readable data — effect declarations (once-per-turn budget, categories, field-value delta) and coverage of which value-producing cards are actually exercised by the written combo lines. Use when deriving combo lines for a deck, when checking whether a combo list misses routes, or when a combo line's field-value ledger needs an external cross-check.
---

# Combo Analyzer

把「做场」从手写散文变成**可核算的模型**。它不判断哪条线更好，只回答两个问题：

1. 这副牌有哪些效果能产出场面？（`effects.json`）
2. 哪些产出效果还没被任何做场线用到？（`combo_coverage.py`）

场值的定义与核算规则见 `deck-analyzer` 的「场值模型」一节，这里只负责把模型落成数据。

## 两个脚本

### `scripts/effects_draft.py` — 生成效果声明草稿

```bash
python effects_draft.py deck_raw.json script_facts.json --cdb cards.cdb -o effects.json
```

每张卡的每个**脚本效果**一行：

| 字段 | 来源 | 说明 |
|---|---|---|
| `card` / `effect` | 卡名 / 序号 | 序号是**脚本里的**注册顺序 |
| `opt` | `script_facts` | `card_name_once` / `once_per_turn` / `none` |
| `event` | `script_facts` | 触发事件，例如 `remove`、`summon_success` |
| `categories` | `script_facts` | 这个效果做什么 |
| `delta` | **待填** | 结算后的场值净变化 |
| `requires` | **待填** | 一句话前提 |

> ⚠️ **脚本的效果序号不等于卡面编号。** 卡面写 ①②③ 的卡，脚本里常常注册 4~5 个 effect
> （同一效果按不同召唤事件各注册一次）。所以 `effects.json` 里的「③」指的是脚本第 3 个，
> 不是卡面③。需要对齐时，在 `note` 里写清卡面编号，不要指望序号。

### `scripts/combo_coverage.py` — 找漏掉的路线

```bash
python combo_coverage.py effects.json deck_analysis.json
```

从 `effects.json` 里挑出产出类效果（`CATEGORY_SEARCH` / `TOHAND` / `SPECIAL_SUMMON` / `SSET`），
再和所有 `combo_lines` 的 `cards_used` 求差集。差集里的卡就是**有产出能力但还没探索过的路线**。

```bash
python combo_coverage.py effects.json deck_analysis.json --strict   # 有遗漏就退出码 1
```

## 典型用法

1. 跑 `deck-parser` 拿到 `script_facts.json`
2. `effects_draft.py` 生成草稿
3. 给产出型效果填 `delta` 和 `requires`（只填进过线的卡，手坑留空）
4. 写 `combo_lines`（schema 见 `deck-analyzer`）
5. **`combo_coverage.py` 查一遍**：有没有哪张能产出的卡一次都没用上
6. 对差集里的卡判断：是漏了路线，还是这张卡本来就不该起手

## 它查得出什么、查不出什么

| 查得出 | 查不出 |
|---|---|
| 哪些产出卡没进过任何线 | 已经写的线**对不对** |
| `cards_used` 和实际步骤不一致 | 一步的效果是否真的能在这时点发动 |
| 卡组里有哪些产出型效果 | 效果之间的依赖顺序 |

**已写的线是否正确，仍然只能靠人读卡面，或者靠模拟器。** 这个 skill 的定位是
「别漏路线」，不是「证明路线成立」。

## 已知的误报

`CATEGORY_SPECIAL_SUMMON` 会把「能特召自己」的手坑（如 PSY骨架装备·γ）也算成产出卡。
遇到这类误报，在 `effects.json` 里给该效果标 `"note": "手坑，不是动点"`，人眼跳过即可。
