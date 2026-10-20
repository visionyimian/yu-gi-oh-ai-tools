#!/usr/bin/env python3
"""精确枚举起手手牌，统计「单卡动 / 二卡动 / 不能动」的真实比例。

为什么需要这个脚本
------------------
单组超几何只能回答「至少摸到 1 张某卡」，回答不了「这 5 张放在一起能不能动」。
而「能动」的定义本身就是手牌级的：A 单卡能动、B 只有配 C 才能动、
某些卡单独上手等于废纸。把这些规则写在组合概率里既不准也不可验证。

40 张主卡组只有 C(40,5)=658008 种起手，完全可以穷举。
所以：agent 负责判断「哪几组牌算动点」，脚本负责把判断精确量化。

规则文件格式（combos.json）
---------------------------
{
  "one_card": [
    {"label": "白兔单卡", "cards": ["码丽丝<兵卒>白兔"]}
  ],
  "two_card": [
    {"label": "无垢 + Link-1 身体",
     "first": ["无限与有限之无垢大艺术", "净化与腐败之无垢大艺术"],
     "second_predicate": "link1_material"}
  ]
}

用法
----
  python hand_matrix.py deck_raw.json combos.json
  python hand_matrix.py deck_raw.json combos.json --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import derive_combos
from combo_scan import link_monsters, load_deck

# 谓词：不是具体卡名，而是「手里有没有满足某个条件的一张牌」
PREDICATES = {
  "link1_material": "手里有能满足某只 Link-1 素材条件的怪兽",
  "link2_material": "手里有能满足某只 Link-2 素材条件的怪兽",
  "ns_body": "手里有可以通常召唤的怪兽",
}

# 一回合只能用一次的资源：规则里声明的次数不能超过这里的预算
EXCLUSIVE_PER_TURN = {"normal_summon": 1, "pendulum_summon": 1}


def _gate_names(deck: dict, max_rating: int) -> set[str]:
  names = set()
  for link in link_monsters(deck):
    if (link["link_rating"] or 99) > max_rating:
      continue
    for card in link["satisfier"]["cards"]:
      names.add(card["name"])
  return names


def resolve_predicate(name: str, deck: dict) -> set[str]:
  """把谓词展开成主卡组卡名集合。"""
  if name == "link1_material":
    return _gate_names(deck, 1)
  if name == "link2_material":
    return _gate_names(deck, 2)
  if name == "ns_body":
    return {c["name"] for c in deck["main"] if c["is_monster"] and not c["cannot_normal_summon"]}
  raise ValueError("未知谓词 {}，可用：{}".format(name, ", ".join(PREDICATES)))


def build_rules(rules: dict, deck: dict) -> list[dict]:
  """把规则文件解析成「触发集合名称」的形式，并校验卡名。"""
  main_names = {c["name"] for c in deck["main"]}
  parsed = []

  def names_of(rule: dict, key: str, predicate_key: str) -> set[str]:
    if key in rule:
      listed = set(rule[key])
      unknown = listed - main_names
      if unknown:
        raise ValueError(
          "规则「{}」里的卡名不在主卡组：{}（额外卡组怪兽不能作为起手件）".format(
            rule.get("label", "?"), ", ".join(sorted(unknown))
          )
        )
      return listed
    if predicate_key in rule:
      return resolve_predicate(rule[predicate_key], deck)
    raise ValueError("规则「{}」缺少 {} 或 {}".format(rule.get("label", "?"), key, predicate_key))

  def resources_of(rule: dict) -> tuple[dict, list[str]]:
    """解析并校验 consumes / locks：一回合只能做一次的资源不能超额。"""
    label = rule.get("label", "?")
    consumes = rule.get("consumes") or {}
    if not isinstance(consumes, dict):
      raise TypeError(f"规则「{label}」的 consumes 必须是对象")
    for key, value in consumes.items():
      if not isinstance(value, int) or value < 0:
        raise ValueError(f"规则「{label}」的 consumes.{key} 必须是非负整数")
      budget = EXCLUSIVE_PER_TURN.get(key)
      if budget is not None and value > budget:
        raise ValueError(f"规则「{label}」声明 {key}={value}，但一回合只能 {budget} 次")
    locks = rule.get("locks") or []
    if not isinstance(locks, list):
      raise TypeError(f"规则「{label}」的 locks 必须是数组")
    return consumes, list(locks)

  for rule in rules.get("one_card") or []:
    consumes, locks = resources_of(rule)
    parsed.append(
      {
        "label": rule.get("label", "单卡动"),
        "first": names_of(rule, "cards", "predicate"),
        "second": None,
        "consumes": consumes,
        "locks": locks,
      }
    )
  for rule in rules.get("two_card") or []:
    consumes, locks = resources_of(rule)
    first = names_of(rule, "first", "first_predicate")
    second = names_of(rule, "second", "second_predicate")
    if not second:
      raise ValueError("规则「{}」的 second 为空".format(rule.get("label", "?")))
    parsed.append(
      {
        "label": rule.get("label", "二卡动"),
        "first": first,
        "second": second,
        "consumes": consumes,
        "locks": locks,
      }
    )
  return parsed


def _distinct_pair(combo: tuple, instances: list[str], first: set[str], second: set[str]) -> bool:
  """手里是否存在两张不同的卡，分别属于 first 与 second。"""
  for i in combo:
    if instances[i] not in first:
      continue
    for j in combo:
      if i != j and instances[j] in second:
        return True
  return False


def enumerate_hands(deck: dict, parsed_rules: list[dict], hand_size: int = 5) -> dict:
  """穷举全部起手，按规则分类。"""
  instances = [c["name"] for c in deck["main"] for _ in range(c["count"])]
  total_cards = len(instances)
  if total_cards == 0:
    raise ValueError("主卡组为空")

  first_masks = [0] * total_cards
  second_masks = [0] * total_cards
  for index, name in enumerate(instances):
    first_bits = 0
    second_bits = 0
    for rule_index, rule in enumerate(parsed_rules):
      if name in rule["first"]:
        first_bits |= 1 << rule_index
      if rule["second"] is not None and name in rule["second"]:
        second_bits |= 1 << rule_index
    first_masks[index] = first_bits
    second_masks[index] = second_bits

  # first 与 second 有交集的规则，需要确认是两张不同的卡（例如「无限 + 无限」）
  overlap = [
    bool(rule["second"]) and bool(rule["first"] & (rule["second"] or set()))
    for rule in parsed_rules
  ]

  by_label: Counter = Counter()
  dead_examples: Counter = Counter()
  dead_total = 0
  total_hands = 0

  for combo in combinations(range(total_cards), hand_size):
    total_hands += 1
    first_bits = 0
    second_bits = 0
    for index in combo:
      first_bits |= first_masks[index]
      second_bits |= second_masks[index]

    matched = None
    for rule_index, rule in enumerate(parsed_rules):
      if not (first_bits >> rule_index) & 1:
        continue
      if rule["second"] is None:
        matched = rule["label"]
        break
      if not (second_bits >> rule_index) & 1:
        continue
      if overlap[rule_index] and not _distinct_pair(
        combo, instances, rule["first"], rule["second"]
      ):
        continue
      matched = rule["label"]
      break

    if matched is None:
      dead_total += 1
      if len(dead_examples) < 200:
        dead_examples[tuple(sorted(instances[i] for i in combo))] += 1
    else:
      by_label[matched] += 1

  def pct(value: int) -> float:
    return round(value / total_hands * 100, 2) if total_hands else 0.0

  one_labels = [r["label"] for r in parsed_rules if r["second"] is None]
  two_labels = [r["label"] for r in parsed_rules if r["second"] is not None]
  one_total = sum(by_label[label] for label in one_labels)
  two_total = sum(by_label[label] for label in two_labels)

  return {
    "deck_size": total_cards,
    "hand_size": hand_size,
    "total_hands": total_hands,
    "one_card": {
      "rate": pct(one_total),
      "by_label": {label: pct(by_label[label]) for label in one_labels},
    },
    "two_card": {
      "rate": pct(two_total),
      "by_label": {label: pct(by_label[label]) for label in two_labels},
    },
    "startable": pct(one_total + two_total),
    "rules": [
      {
        "label": rule["label"],
        "kind": "one" if rule["second"] is None else "two",
        "consumes": rule["consumes"],
        "locks": rule["locks"],
        "rate": pct(by_label[rule["label"]]),
      }
      for rule in parsed_rules
    ],
    "dead": {
      "rate": pct(dead_total),
      "hands": dead_total,
      "examples": [
        {"cards": list(hand), "hands": count} for hand, count in dead_examples.most_common(5)
      ],
    },
  }


def render(result: dict, threshold: float) -> str:
  lines = []
  lines.append(
    "手牌 {} 张 ｜ 主卡组 {} 张 ｜ 总手牌 {:,} 种".format(
      result["hand_size"], result["deck_size"], result["total_hands"]
    )
  )
  lines.append("")
  lines.append("单卡动点  {:5.2f}%".format(result["one_card"]["rate"]))
  for label, rate in result["one_card"]["by_label"].items():
    lines.append(f"    {label:<28} {rate:5.2f}%")
  lines.append("二卡动点  {:5.2f}%".format(result["two_card"]["rate"]))
  for label, rate in result["two_card"]["by_label"].items():
    lines.append(f"    {label:<28} {rate:5.2f}%")
  lines.append("能动合计  {:5.2f}%".format(result["startable"]))
  lines.append("不能动    {:5.2f}%".format(result["dead"]["rate"]))

  if result.get("rules"):
    lines.append("")
    lines.append("资源占用：")
    for rule in result["rules"]:
      used = ", ".join(f"{key}×{value}" for key, value in rule["consumes"].items()) or "无"
      locks = "，自锁：" + "/".join(rule["locks"]) if rule["locks"] else ""
      lines.append(f"    {rule['label']:<28} {used}{locks}")

  if result["dead"]["rate"] > threshold:
    lines.append("")
    lines.append(
      "⚠ 死手率 {:.2f}% 高于阈值 {:.1f}%：这通常意味着还有未识别的二卡动点，"
      "请回到 combo_scan 检查「需求 → 满足者」候选，不要直接把当前数字写进报告。".format(
        result["dead"]["rate"], threshold
      )
    )
  if result["dead"]["examples"]:
    lines.append("")
    lines.append("最常见的死手：")
    for example in result["dead"]["examples"][:3]:
      lines.append("    " + " + ".join(example["cards"]))
  return "\n".join(lines)


def main(argv: list[str] | None = None):
  parser = argparse.ArgumentParser(description="精确枚举起手手牌，统计动点与死手率")
  parser.add_argument("deck", help="deck_raw.json 或 deck_raw.csv")
  parser.add_argument("rules", nargs="?", help="combos.json；用 --derive 时可省略")
  parser.add_argument("--derive", action="store_true", help="自动推导动点规则，不读 combos.json")
  parser.add_argument("--facts", type=Path, help="script_facts.json（--derive 需要）")
  parser.add_argument("--candidates", type=Path, help="combo_candidates.json（--derive 需要）")
  parser.add_argument("--cdb", type=Path, help="cards.cdb（--derive 需要）")
  parser.add_argument("--write-rules", type=Path, help="把推导出的规则另存一份")
  parser.add_argument("--hand-size", type=int, default=5, help="起手张数（默认 5）")
  parser.add_argument(
    "--max-dead-rate", type=float, default=15.0, help="死手率告警阈值（默认 15%%）"
  )
  parser.add_argument("--strict", action="store_true", help="死手率超过阈值时以退出码 1 结束")
  parser.add_argument("--json", action="store_true", help="输出 JSON")
  parser.add_argument("--output", "-o", help="把 JSON 结果写入文件")
  args = parser.parse_args(argv)

  deck = load_deck(args.deck)
  if args.derive:
    required = (("--facts", args.facts), ("--candidates", args.candidates), ("--cdb", args.cdb))
    missing = [name for name, value in required if value is None]
    if missing:
      print(f"错误：--derive 需要 {' '.join(missing)}", file=sys.stderr)
      return 1
    rules = derive_combos.derive(
      deck,
      json.loads(args.facts.read_text(encoding="utf-8-sig")),
      json.loads(args.candidates.read_text(encoding="utf-8-sig")),
      derive_combos.load_names(args.cdb),
    )
    if args.write_rules:
      args.write_rules.write_text(
        json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
      )
    print(
      f"自动推导动点：{len(rules['one_card'])} 条单卡动 / "
      f"{len(rules['two_card'])} 条二卡动（未复核）"
    )
  else:
    if not args.rules:
      print("错误：需要 combos.json，或加 --derive 自动推导", file=sys.stderr)
      return 1
    rules = json.loads(Path(args.rules).read_text(encoding="utf-8-sig"))

  try:
    parsed = build_rules(rules, deck)
    result = enumerate_hands(deck, parsed, args.hand_size)
  except (ValueError, TypeError) as error:
    print(f"错误：{error}", file=sys.stderr)
    return 1

  result["dead"]["threshold"] = args.max_dead_rate
  result["dead"]["over_threshold"] = result["dead"]["rate"] > args.max_dead_rate

  if args.output:
    Path(args.output).write_text(
      json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
  if args.json:
    print(json.dumps(result, ensure_ascii=False, indent=2))
  else:
    print(render(result, args.max_dead_rate))

  if args.strict and result["dead"]["over_threshold"]:
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main())
