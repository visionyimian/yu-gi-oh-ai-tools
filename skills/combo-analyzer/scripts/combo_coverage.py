#!/usr/bin/env python3
"""找出「有产出能力但还没进过任何做场线」的卡。

做场线是手写的，很容易漏掉整条路线。这个脚本反过来查：从效果声明里挑出
**产出类**的卡（检索 / 特召 / 盖放），看它们在 `combo_lines` 的 `cards_used`
里出现过没有。没出现过的，就是还没被探索的路线。

它不判断「这条线对不对」——只负责把「还有哪些卡没被用过」摆出来。

用法::

    python combo_coverage.py effects.json deck_analysis.json
    python combo_coverage.py effects.json deck_analysis.json --strict
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 与 derive_combos 保持一致：这些类别说明这张卡能产出场面
PRODUCING = {
  "CATEGORY_SEARCH",
  "CATEGORY_TOHAND",
  "CATEGORY_SPECIAL_SUMMON",
  "CATEGORY_SSET",
}


def producing_cards(effects: dict) -> dict[str, list[str]]:
  """卡名 → 它的产出类效果类别。"""
  result: dict[str, list[str]] = {}
  for entry in effects["effects"]:
    hits = sorted(set(entry.get("categories") or []) & PRODUCING)
    if hits:
      result.setdefault(entry["card"], [])
      result[entry["card"]] = sorted(set(result[entry["card"]]) | set(hits))
  return result


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="报告还没进过做场线的产出型卡片。")
  parser.add_argument("effects", type=Path, help="effects.json")
  parser.add_argument("analysis", type=Path, help="deck_analysis.json")
  parser.add_argument("--strict", action="store_true", help="有未覆盖的卡就以退出码 1 结束")
  args = parser.parse_args(argv)

  effects = json.loads(args.effects.read_text(encoding="utf-8-sig"))
  analysis = json.loads(args.analysis.read_text(encoding="utf-8-sig"))

  lines = analysis.get("combo_lines") or []
  if not lines:
    print("错误：deck_analysis.json 里没有 combo_lines", file=sys.stderr)
    return 1

  candidates = producing_cards(effects)
  used: dict[str, list[str]] = {}
  for line in lines:
    for card in line.get("cards_used") or []:
      used.setdefault(card, []).append(line.get("name", "?"))

  covered = sorted(set(candidates) & set(used))
  missing = sorted(set(candidates) - set(used))

  print(f"做场线 {len(lines)} 条，共用到 {len(used)} 张卡")
  print(f"产出型卡片 {len(candidates)} 张，其中 {len(covered)} 张进过做场线\n")

  width = max((len(name) for name in candidates), default=8)
  for name in covered:
    print(f"  [用过] {name:<{width}}  {'、'.join(candidates[name])}")
  for name in missing:
    print(f"  [未用] {name:<{width}}  {'、'.join(candidates[name])}")

  print()
  if missing:
    print(f"[COVERAGE] {len(missing)} 张产出卡还没有任何做场线用到：")
    for name in missing:
      print(f"  - {name}")
    if args.strict:
      return 1
  else:
    print("[COVERAGE] 所有产出型卡片都至少出现在一条做场线里")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
