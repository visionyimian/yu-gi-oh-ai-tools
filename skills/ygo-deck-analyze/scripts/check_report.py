#!/usr/bin/env python3
"""校验 report.md 是否覆盖了 deck_analysis.json 里的每一条结论。

报告是手写的，而分析 JSON 是结构化的：写报告时很容易漏掉表格里的一两行。
这个脚本把「JSON 里有的条目」当作必现清单，逐项在报告正文里查找。

只检查**标识性文字**（卡名、维度键），不检查 reason 之类的自由文本——
那些是重新表述的，做子串匹配只会制造假阳性。

用法::

    python check_report.py deck_analysis.json report.md
    python check_report.py deck_analysis.json report.md --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCORE_KEYS = ("consistency", "ceiling", "resilience", "going_second", "grind", "route_diversity")


def collect(analysis: dict) -> list[tuple[str, str]]:
  """从分析 JSON 里提取必须在报告中出现的条目。"""
  items: list[tuple[str, str]] = []

  for card in analysis.get("first_turn_board", {}).get("typical_endboard") or []:
    items.append(("终场卡片", card.get("card_name", "")))

  vulnerability = analysis.get("endboard_vulnerability") or {}
  for threat in vulnerability.get("board_breaker_threats") or []:
    items.append(("盘面突破", threat.get("threat", "")))

  for entry in (analysis.get("handtrap_vulnerability") or {}).get("analysis") or []:
    items.append(("手坑", entry.get("handtrap", "")))

  for point in analysis.get("chokepoints") or []:
    items.append(("Chokepoint", point.get("card_involved", "")))

  for tool in (analysis.get("going_second") or {}).get("board_breaking_tools") or []:
    items.append(("后攻工具", tool.get("card", "")))

  for line in analysis.get("combo_lines") or []:
    items.append(("做场步骤", line.get("name", "")))

  score = analysis.get("score") or {}
  for key in SCORE_KEYS:
    if key in score:
      items.append(("六维评分", key))

  return [(section, text) for section, text in items if text]


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="检查报告是否覆盖了分析 JSON 的每一条结论。")
  parser.add_argument("analysis", type=Path, help="deck_analysis.json")
  parser.add_argument("report", type=Path, help="report.md")
  parser.add_argument("--verbose", action="store_true", help="列出全部条目而不是只列缺失")
  args = parser.parse_args(argv)

  analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
  report = args.report.read_text(encoding="utf-8")
  items = collect(analysis)

  if not items:
    print("分析 JSON 里没有可校验的条目", file=sys.stderr)
    return 1

  by_section: dict[str, list[str]] = {}
  for section, text in items:
    by_section.setdefault(section, []).append(text)

  failed = 0
  width = max(len(section) for section in by_section)
  for section, texts in by_section.items():
    missing = [text for text in texts if text not in report]
    covered = len(texts) - len(missing)
    if missing:
      failed += 1
      print(f"[FAIL] {section:<{width}}  {covered}/{len(texts)}  缺：{'、'.join(missing)}")
    else:
      print(f"[PASS] {section:<{width}}  {covered}/{len(texts)}")
      if args.verbose:
        print(f"       {'、'.join(texts)}")

  print()
  if failed:
    print(f"[VALIDATION FAILED] {failed} 个分区有遗漏，补完再交付")
    return 1
  print(f"[VALIDATION PASSED] {len(items)} 条结论全部出现在报告中")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
