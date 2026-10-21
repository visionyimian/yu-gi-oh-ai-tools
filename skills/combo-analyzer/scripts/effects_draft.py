#!/usr/bin/env python3
"""从 script_facts.json 生成 effects.json 草稿：每张卡的每个效果一行。

`effects.json` 是 combo-analyzer 的核心模型——把「这张卡的哪个效果，一回合能用几次，
产出什么」写成机器能读的表。草稿只填能从脚本读出来的部分（次数、事件、类别），
`delta`（场值变化）和 `requires`（前置条件）留空，由人/agent 补齐。

用法::

    python effects_draft.py deck_raw.json script_facts.json --cdb cards.cdb -o effects.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

NUMERALS = "①②③④⑤⑥⑦⑧⑨⑩"


def load_names(cdb: Path) -> dict[int, str]:
  connection = sqlite3.connect(cdb)
  try:
    return {row[0]: row[1] for row in connection.execute("SELECT id, name FROM texts")}
  finally:
    connection.close()


def build(deck: dict, facts: dict, names: dict[int, str]) -> dict:
  by_name = {names.get(card["id"], ""): card for card in facts["cards"]}
  effects: list[dict] = []

  for card in deck["main"]:
    name = card["name"]
    fact = by_name.get(name)
    if not fact:
      continue
    for index, effect in enumerate(fact.get("effects") or [], start=1):
      effects.append(
        {
          "card": name,
          "effect": NUMERALS[index - 1] if index <= len(NUMERALS) else f"#{index}",
          "opt": effect.get("opt", "none"),
          "event": (effect.get("event") or "").replace("EVENT_", "").lower(),
          "categories": effect.get("categories") or [],
          "delta": None,
          "requires": "",
          "note": "",
        }
      )

  return {
    "deck": "",
    "effects": effects,
    "notes": [
      "delta = 这个效果结算完，自己场上场值的净变化（非连接怪兽 1，连接怪兽取标记数）。",
      "含 cost 的效果，delta 记整次结算的净变化（例如「除外自己场上一只」记负数）。",
      "requires 写一句话前提，例如「墓地有码丽丝怪兽」。",
      "delta 留 null 表示这条效果不参与场值核算（手坑、抽滤等）。",
    ],
  }


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="从 script_facts 生成 effects.json 草稿。")
  parser.add_argument("deck", type=Path, help="deck_raw.json")
  parser.add_argument("facts", type=Path, help="script_facts.json")
  parser.add_argument("--cdb", type=Path, required=True, help="cards.cdb（id → 卡名）")
  parser.add_argument("-o", "--out", type=Path, help="输出文件，默认打印")
  args = parser.parse_args(argv)

  deck = json.loads(args.deck.read_text(encoding="utf-8-sig"))
  facts = json.loads(args.facts.read_text(encoding="utf-8-sig"))
  result = build(deck, facts, load_names(args.cdb))

  body = json.dumps(result, ensure_ascii=False, indent=2)
  if args.out:
    args.out.write_text(body + "\n", encoding="utf-8")
    print(f"已写入 {args.out}：{len(result['effects'])} 条效果声明（delta 待填）")
  else:
    sys.stdout.write(body + "\n")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
