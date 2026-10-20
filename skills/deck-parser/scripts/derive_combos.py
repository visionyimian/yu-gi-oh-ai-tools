#!/usr/bin/env python3
"""从脚本事实与扫描候选自动推导 combos.json，不需要人手写。

推导规则（全部来自机器可读的数据，不读中文文本判断语义）：

**单卡动点**：一张主卡组卡只要有一个「产出类」效果，且不依赖外部事件。
产出类 = `SetCategory` 里含以下任一项：

- `CATEGORY_SEARCH` / `CATEGORY_TOHAND` —— 检索
- `CATEGORY_SPECIAL_SUMMON` —— 产出身体
- `CATEGORY_SSET` —— 从卡组盖放

**二卡动点**：`combo_scan` 标出 `self_trigger: false` 的卡（它要等外部事件，比如
「连接召唤成功」），用它的 enabler 作为第二张：

- enabler 是 Link 怪兽 → 用 `link1_material` / `link2_material` 谓词
- enabler 是主卡组卡 → 直接写卡名

**通召占用**：产出效果是「召唤成功时」触发的记 1，其余记 0。这是近似值，
所以每条规则都带 `reason`，方便复核。

用法::

    python derive_combos.py deck_raw.json script_facts.json combo_candidates.json \
        --cdb cards.cdb -o combos.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PRODUCING = {
  "CATEGORY_SEARCH",
  "CATEGORY_TOHAND",
  "CATEGORY_SPECIAL_SUMMON",
  "CATEGORY_SSET",
}
ACTIVE_KINDS = {
  "ignition",
  "trigger_optional",
  "trigger_mandatory",
  "activation",
}
SUMMON_EVENTS = {"EVENT_SUMMON_SUCCESS", "EVENT_SPSUMMON_SUCCESS"}

PREDICATE_BY_RATING = {1: "link1_material", 2: "link2_material"}


def load_names(cdb: Path) -> dict[int, str]:
  connection = sqlite3.connect(cdb)
  try:
    return {row[0]: row[1] for row in connection.execute("SELECT id, name FROM texts")}
  finally:
    connection.close()


def producing_effects(fact: dict) -> list[dict]:
  """挑出会产出资源的那些效果。"""
  return [
    effect
    for effect in fact.get("effects") or []
    if effect.get("kind") in ACTIVE_KINDS and set(effect.get("categories") or []) & PRODUCING
  ]


def consumptions(effects: list[dict], locks: list[str]) -> tuple[dict, list[str]]:
  """近似判断这条线要不要吃通召。"""
  needs_ns = any(effect.get("event") in SUMMON_EVENTS for effect in effects)
  consumes = {"normal_summon": 1} if needs_ns else {}
  return consumes, list(locks)


def derive(deck: dict, facts: dict, candidates: dict, names: dict[int, str]) -> dict:
  main_cards = {card["name"]: card for card in deck["main"]}
  by_name = {names.get(card["id"], ""): card for card in facts["cards"]}

  external = {
    trigger["card"]: trigger
    for trigger in candidates.get("triggers") or []
    if not trigger.get("self_trigger", True)
  }

  one_card: list[dict] = []
  deferred: dict[str, dict] = {}

  for name in sorted(main_cards):
    card = main_cards[name]
    fact = by_name.get(name)
    if fact is None:
      continue
    # 陷阱卡先手无法单独启动：要么得先盖一回合，要么得靠别的卡把怪除外
    if "陷阱卡" in (card.get("type") or ""):
      continue
    # 触发依赖外部事件（比如「连接召唤成功时」）→ 交给二卡动处理
    if name in external:
      deferred[name] = external[name]
      continue
    effects = producing_effects(fact)
    if not effects:
      continue
    consumes, locks = consumptions(effects, fact.get("indirect_restrictions") or [])
    categories = sorted({cat for effect in effects for cat in effect.get("categories") or []})
    one_card.append(
      {
        "label": f"{name}单卡",
        "cards": [name],
        "consumes": consumes,
        "locks": locks,
        "reason": f"产出类效果 {categories}，kind={effects[0]['kind']}",
      }
    )

  two_card: list[dict] = []
  for name, trigger in sorted(deferred.items()):
    enablers = trigger.get("enablers") or []
    if not enablers:
      continue

    ratings = {enabler.get("link_rating") for enabler in enablers if enabler.get("link_rating")}
    predicate = PREDICATE_BY_RATING.get(min(ratings)) if ratings else None

    rule: dict = {
      "label": f"{name}＋触发件",
      "first": [name],
      "consumes": {},
      "locks": [],
      "reason": f"需求「{trigger.get('text')}」由 {len(enablers)} 种卡满足",
    }
    if predicate:
      rule["second_predicate"] = predicate
      rule["reason"] += f"（统一为 {predicate}）"
    else:
      in_main = [enabler["card"] for enabler in enablers if enabler["card"] in main_cards]
      if not in_main:
        continue
      rule["second"] = in_main[:6]
      rule["reason"] += "（按主卡组卡名）"
    two_card.append(rule)

  return {
    "one_card": one_card,
    "two_card": two_card,
    "derivation": {
      "source": "script_facts.categories + combo_scan.triggers",
      "main_cards": len(main_cards),
      "deferred_to_two_card": sorted(deferred),
    },
  }


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="自动推导 combos.json（动点规则）。")
  parser.add_argument("deck", type=Path, help="deck_raw.json")
  parser.add_argument("facts", type=Path, help="script_facts.json")
  parser.add_argument("candidates", type=Path, help="combo_candidates.json")
  parser.add_argument("--cdb", type=Path, required=True, help="cards.cdb（id → 卡名）")
  parser.add_argument("-o", "--out", type=Path, help="输出文件，默认打印")
  args = parser.parse_args(argv)

  deck = json.loads(args.deck.read_text(encoding="utf-8"))
  facts = json.loads(args.facts.read_text(encoding="utf-8"))
  candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
  names = load_names(args.cdb)

  result = derive(deck, facts, candidates, names)
  body = json.dumps(result, ensure_ascii=False, indent=2)

  if args.out:
    args.out.write_text(body + "\n", encoding="utf-8")
    print(
      f"已写入 {args.out}：{len(result['one_card'])} 条单卡动，{len(result['two_card'])} 条二卡动"
    )
    for rule in result["one_card"] + result["two_card"]:
      print(f"  {rule['label']:<24} {rule['reason']}")
  else:
    sys.stdout.write(body + "\n")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
