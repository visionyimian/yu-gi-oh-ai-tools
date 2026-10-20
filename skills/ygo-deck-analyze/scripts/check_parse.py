#!/usr/bin/env python3
"""Step 4.5 的机械化实现：校验 deck_parsed.json 与各产物的内部一致性。

Step 4.5 原先是一段要 agent 手工执行的检查清单，漏做也没人发现。这个脚本把它变成
可以跑的断言：

1. **endboard 覆盖** —— parser 标为终场的卡，analyzer 的终场里必须都提到
2. **hand_matrix 一致性** —— `deck_parsed.json` 里的能动率/死手率必须与穷举结果一致
3. **脚本事实一致性** —— `once_per_turn_type` 必须等于脚本读出的 `opt`；
   `custom` 的卡必须标 `script_custom`
4. **script 块完整性** —— 有脚本的卡必须带 `script`，且与脚本事实一致

用法::

    python check_parse.py --parsed deck_parsed.json --analysis deck_analysis.json \
        --matrix hand_matrix.json --facts script_facts.json --cdb cards.cdb
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

TRIGGER_KINDS = {"trigger_optional", "trigger_mandatory"}
END_BOARD_ROLES = {"endboard", "both"}


def iter_cards(parsed: dict):
  """遍历 deck_parsed.json 里所有带卡名的条目，去重。"""
  seen: set[str] = set()
  for engine in parsed.get("engines") or []:
    for card in engine.get("cards") or []:
      if card.get("name") and card["name"] not in seen:
        seen.add(card["name"])
        yield card
  for key in ("starters", "extenders", "handtraps"):
    for card in (parsed.get(key) or {}).get("cards") or []:
      if card.get("name") and card["name"] not in seen:
        seen.add(card["name"])
        yield card
  for card in parsed.get("maindeck_endboard") or []:
    if card.get("name") and card["name"] not in seen:
      seen.add(card["name"])
      yield card


def summarize(fact: dict) -> dict:
  """与 deck-parser 回填时的聚合方式保持一致。"""
  effects = fact.get("effects") or []
  triggers = [effect for effect in effects if effect.get("kind") in TRIGGER_KINDS]
  return {
    "kinds": [effect.get("kind") for effect in effects],
    "targets": any(effect.get("targets") for effect in effects),
    "has_cost": any(effect.get("has_cost") for effect in effects),
    "no_miss_timing": (
      all(effect.get("no_miss_timing") for effect in triggers) if triggers else None
    ),
  }


def load_names(cdb: Path) -> dict[int, str]:
  connection = sqlite3.connect(cdb)
  try:
    return {row[0]: row[1] for row in connection.execute("SELECT id, name FROM texts")}
  finally:
    connection.close()


def check_endboard(parsed: dict, analysis: dict) -> tuple[bool, str]:
  declared = {card["name"] for card in parsed.get("maindeck_endboard") or []}
  declared |= {
    card["name"]
    for card in parsed.get("extradeck_monsters") or []
    if card.get("role") in END_BOARD_ROLES
  }
  covered = {
    card.get("card_name")
    for card in (analysis.get("first_turn_board") or {}).get("typical_endboard") or []
  }
  missing = sorted(declared - covered)
  detail = f"{len(declared) - len(missing)}/{len(declared)}"
  if missing:
    detail += "  缺：" + "、".join(missing)
  return not missing, detail


def check_matrix(parsed: dict, matrix: dict) -> tuple[bool, str]:
  recorded = parsed.get("hand_matrix") or {}
  expected_startable = f"{matrix['startable']:.2f}%"
  expected_dead = f"{matrix['dead']['rate']:.2f}%"
  problems = []
  if recorded.get("startable_rate") != expected_startable:
    problems.append(f"能动率 记录 {recorded.get('startable_rate')} / 实际 {expected_startable}")
  if recorded.get("dead_rate") != expected_dead:
    problems.append(f"死手率 记录 {recorded.get('dead_rate')} / 实际 {expected_dead}")
  detail = f"{recorded.get('startable_rate')} / {recorded.get('dead_rate')}"
  if problems:
    detail = "；".join(problems)
  return not problems, detail


def check_facts(parsed: dict, facts_by_name: dict) -> tuple[bool, str]:
  problems = []
  checked = 0
  for card in iter_cards(parsed):
    fact = facts_by_name.get(card["name"])
    if fact is None:
      continue
    checked += 1
    if fact["opt"] == "custom":
      if card.get("once_per_turn_source") != "script_custom":
        problems.append(f"{card['name']}: custom 但缺 script_custom")
    elif card.get("once_per_turn_type") != fact["opt"]:
      problems.append(f"{card['name']}: 声明 {card.get('once_per_turn_type')} / 脚本 {fact['opt']}")
  detail = f"{checked - len(problems)}/{checked}" if checked else "无可比对卡片"
  if problems:
    detail += "  " + "；".join(problems[:3])
  return not problems, detail


def check_script_block(parsed: dict, facts_by_name: dict) -> tuple[bool, str]:
  problems = []
  checked = 0
  for card in iter_cards(parsed):
    fact = facts_by_name.get(card["name"])
    if fact is None:
      continue
    checked += 1
    block = card.get("script")
    if block is None:
      problems.append(f"{card['name']}: 缺 script 块")
      continue
    expected = summarize(fact)
    if block.get("kinds") != expected["kinds"]:
      problems.append(f"{card['name']}: kinds 不一致")
    for key in ("targets", "has_cost", "no_miss_timing"):
      if block.get(key) != expected[key]:
        problems.append(f"{card['name']}: {key} 不一致")
  detail = f"{checked - len(problems)}/{checked}" if checked else "无可比对卡片"
  if problems:
    detail += "  " + "；".join(problems[:3])
  return not problems, detail


def check_combo_lines(parsed: dict, analysis: dict, rules: dict | None) -> tuple[bool, str]:
  """做场线里提到的卡必须在卡组里；起手必须是 combos.json 认过的动点。"""
  lines = analysis.get("combo_lines") or []
  if not lines:
    return True, "（未提供）"

  deck_names = set()
  for engine in parsed.get("engines") or []:
    for card in engine.get("cards") or []:
      deck_names.add(card["name"])
  for card in parsed.get("extradeck_monsters") or []:
    deck_names.add(card["name"])
  for card in parsed.get("maindeck_endboard") or []:
    deck_names.add(card["name"])

  starters: set[str] = set()
  if rules:
    for rule in rules.get("one_card") or []:
      starters.update(rule.get("cards") or [])
    for rule in rules.get("two_card") or []:
      starters.update(rule.get("first") or [])

  problems = []
  acknowledged = []
  for line in lines:
    name = line.get("name", "?")
    for used in line.get("cards_used") or []:
      if used not in deck_names:
        problems.append(f"{name}：卡组里没有「{used}」")
    for end in line.get("endboard") or []:
      if end not in deck_names:
        problems.append(f"{name}：终场「{end}」不在卡组里")
    if starters and line.get("starter") not in starters:
      # 推导器会漏掉某些动点；作者必须写明原因才算数，不能默默不一致
      if line.get("starter_note"):
        acknowledged.append(name)
      else:
        problems.append(f"{name}：起手「{line.get('starter')}」不在 combos.json 里")

  detail = f"{len(lines)} 条"
  if acknowledged:
    detail += f"（{len(acknowledged)} 条标注了推导差异）"
  if problems:
    detail += "  " + "；".join(problems[:3])
  return not problems, detail


def check_field_value(analysis: dict) -> tuple[bool, str]:
  """场值账本要能对上：每一步的增减都要有依据，峰值要和声明一致。"""
  lines = analysis.get("combo_lines") or []
  tracked = [line for line in lines if any(isinstance(s, dict) for s in line.get("steps") or [])]
  if not tracked:
    return True, "（未提供场值步骤）"

  problems = []
  for line in tracked:
    name = line.get("name", "?")
    steps = [step for step in line["steps"] if isinstance(step, dict)]
    values = [step.get("field_value") for step in steps]
    if any(value is None for value in values):
      problems.append(f"{name}：有步骤没写 field_value")
      continue

    peak = line.get("peak_field_value")
    if peak is not None and max(values) != peak:
      problems.append(f"{name}：峰值声明 {peak}，实际 {max(values)}")

    for index in range(1, len(steps)):
      before, after = values[index - 1], values[index]
      if after > before and not steps[index].get("gain"):
        problems.append(f"{name}：第 {index + 1} 步场值 {before}→{after} 但没写 gain")
      # 场值可以花掉：拿高标记的连接怪兽做低标记的素材时，差额要写明换到了什么
      if after < before and not steps[index].get("spend"):
        problems.append(f"{name}：第 {index + 1} 步场值 {before}→{after} 但没写 spend")

  detail = (
    f"{len(tracked)} 条" if not problems else f"{len(tracked)} 条  " + "；".join(problems[:3])
  )
  return not problems, detail


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Step 4.5：校验 deck_parsed.json 的内部一致性。")
  parser.add_argument("--parsed", type=Path, required=True, help="deck_parsed.json")
  parser.add_argument("--analysis", type=Path, required=True, help="deck_analysis.json")
  parser.add_argument("--matrix", type=Path, required=True, help="hand_matrix.json")
  parser.add_argument("--facts", type=Path, required=True, help="script_facts.json")
  parser.add_argument("--cdb", type=Path, required=True, help="cards.cdb（用于 id → 卡名）")
  parser.add_argument("--rules", type=Path, help="combos.json；提供时校验做场线的起手")
  args = parser.parse_args(argv)

  parsed = json.loads(args.parsed.read_text(encoding="utf-8"))
  analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
  matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
  facts = json.loads(args.facts.read_text(encoding="utf-8"))
  rules = json.loads(args.rules.read_text(encoding="utf-8-sig")) if args.rules else None

  names = load_names(args.cdb)
  facts_by_name = {names.get(card["id"], ""): card for card in facts["cards"]}

  results = [
    ("endboard 覆盖", *check_endboard(parsed, analysis)),
    ("hand_matrix", *check_matrix(parsed, matrix)),
    ("脚本事实一致性", *check_facts(parsed, facts_by_name)),
    ("script 块完整性", *check_script_block(parsed, facts_by_name)),
    ("做场线", *check_combo_lines(parsed, analysis, rules)),
    ("场值账本", *check_field_value(analysis)),
  ]

  width = max(len(name) for name, _, _ in results)
  failed = 0
  for name, ok, detail in results:
    if not ok:
      failed += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name:<{width}}  {detail}")

  if matrix.get("dead", {}).get("over_threshold"):
    print(
      f"[WARN] 死手率 {matrix['dead']['rate']:.2f}% 超过阈值："
      "必须回 Step 3.1 复查是否漏了二卡动点，并在 TODO.md 里记下复查结论"
    )

  print()
  if failed:
    print(f"[VALIDATION FAILED] {failed} 项不通过")
    return 1
  print(f"[VALIDATION PASSED] {len(results)} 项检查全部通过")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
