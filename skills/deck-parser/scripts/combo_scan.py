#!/usr/bin/env python3
"""扫描卡组中的「需求 → 满足者」关系，为二卡动点（combo starter）提供候选。

为什么需要这个脚本
------------------
单卡动点可以逐卡读出来，二卡动点却依赖「A 的需求能不能被 B 满足」这种跨卡关系。
40 张主卡组有 780 对组合，靠人（或模型）逐对检查一定会漏。

典型漏检：某张卡写着「这张卡是除外状态，连接怪兽特殊召唤的场合才能发动」，
它的触发条件不是某张具体卡，而是「一次连接召唤」。额外卡组里的 Link-1
（素材是「攻击力1000以下的通常召唤怪兽」）就足以满足它——但这条关系
不会出现在任何一张卡的文本里，只能靠联结发现。

这个脚本只做机械联结，不做判断：它列出「谁需要什么／谁能满足」并附证据，
由 deck-parser 的 agent 判断这些候选是否真的成立。

用法
----
  python combo_scan.py deck_raw.json
  python combo_scan.py deck_raw.csv -o candidates.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 卡牌模型 ---

MATERIAL_PATTERNS = (
  (re.compile(r"^包含融合·同调·超量·连接怪兽的怪兽(\d+)只以上$"), "ed_monster"),
  (re.compile(r"^通常召唤的攻击力(\d+)以下的怪兽(\d+)只$"), "ns_max_atk"),
  (re.compile(r"^(\d+)星以下的(.+?)族怪兽(\d+)只$"), "race_level"),
  (re.compile(r"^包含「(.+?)」怪兽的怪兽(\d+)只以上$"), "archetype_min"),
  (re.compile(r"^包含「(.+?)」怪兽的怪兽(\d+)只$"), "archetype"),
  (re.compile(r"^(.+?)族怪兽(\d+)只以上$"), "race_min"),
  (re.compile(r"^(.+?)族怪兽(\d+)只$"), "race"),
  (re.compile(r"^连接怪兽以外的怪兽(\d+)只$"), "nonlink"),
  (re.compile(r"^效果怪兽(\d+)只以上$"), "effect_min"),
  (re.compile(r"^效果怪兽(\d+)只$"), "effect"),
  (re.compile(r"^卡名不同的怪兽(\d+)只$"), "different_names"),
  (re.compile(r"^怪兽(\d+)只以上$"), "any_min"),
  (re.compile(r"^怪兽(\d+)只$"), "any"),
)

# 触发条件：这些文本意味着「需要某个外部动作才能启动」
TRIGGER_PATTERNS = (
  ("融合·连接怪兽特殊召唤的场合", "fusion_link_summon", "需要一次融合或连接召唤"),
  ("同调·连接怪兽特殊召唤的场合", "synchro_link_summon", "需要一次同调或连接召唤"),
  ("超量·连接怪兽特殊召唤的场合", "xyz_link_summon", "需要一次超量或连接召唤"),
  ("连接怪兽特殊召唤的场合", "link_summon", "需要一次连接召唤"),
  ("怪兽特殊召唤的场合", "any_summon", "需要一次特殊召唤"),
  ("召唤·特殊召唤的场合", "normal_special_summon", "需要一次召唤或特殊召唤"),
  ("被除外的场合", "banished", "需要一张能把它除外的卡"),
  ("被送去墓地的场合", "sent_to_gy", "需要一张能把它送去墓地的卡"),
  ("被破坏的场合", "destroyed", "需要一张能破坏它的卡"),
)

LINK_TRIGGER_KINDS = {
  "fusion_link_summon",
  "synchro_link_summon",
  "xyz_link_summon",
  "link_summon",
}

# 噪音较大、默认折叠的触发：它们几乎对每张卡都成立，信息量低
WEAK_TRIGGER_KINDS = {"any_summon", "normal_special_summon", "sent_to_gy", "destroyed"}


def _int_or_none(value) -> int | None:
  if value is None or value == "":
    return None
  try:
    return int(value)
  except (TypeError, ValueError):
    return None


def normalize_card(raw: dict, section: str) -> dict:
  """把 CSV 行或 JSON 对象规整成统一的卡牌结构。"""
  type_text = raw.get("type") or ""
  types = [t for t in type_text.split("|") if t]
  archetypes = [a for a in (raw.get("archetypes") or "").split("|") if a]
  return {
    "name": raw.get("name", ""),
    "desc": raw.get("desc", "") or "",
    "atk": _int_or_none(raw.get("atk")),
    "def": _int_or_none(raw.get("def")),
    "level": _int_or_none(raw.get("level")),
    "race": raw.get("race") or "",
    "attribute": raw.get("attribute") or "",
    "types": types,
    "archetypes": archetypes,
    "count": int(raw.get("count") or 1),
    "section": section,
    "is_monster": "怪兽卡" in types,
    "is_link": "怪兽卡" in types and "连接" in types,
    "is_trap": "陷阱卡" in types,
    "is_spell": "魔法卡" in types,
    "is_effect": "效果" in types,
    "is_tuner": "调整" in types,
    "cannot_normal_summon": "特殊召唤" in types,
  }


def load_deck(path: str) -> dict:
  """读取 deck_raw.json（推荐，含 archetypes）或 deck_raw.csv。"""
  text_path = Path(path)
  if text_path.suffix.lower() == ".json":
    data = json.loads(text_path.read_text(encoding="utf-8-sig"))
    deck = {}
    for section in ("main", "extra", "side"):
      deck[section] = [normalize_card(c, section) for c in data.get(section) or []]
    return deck

  deck = {"main": [], "extra": [], "side": []}
  with text_path.open(encoding="utf-8-sig", newline="") as handle:
    for row in csv.DictReader(handle):
      section = (row.get("deck") or "main").strip().lower()
      if section not in deck:
        section = "main"
      deck[section].append(normalize_card(row, section))
  return deck


# ------------------------------------------------------------ 素材条件解析 ---


def parse_material(line: str) -> dict:
  """解析额外卡组怪兽的第一行素材要求。"""
  cleaned = line.strip().rstrip("。")
  for pattern, kind in MATERIAL_PATTERNS:
    match = pattern.match(cleaned)
    if not match:
      continue
    groups = match.groups()
    if kind == "ns_max_atk":
      return {"kind": kind, "max_atk": int(groups[0]), "count": int(groups[1]), "raw": cleaned}
    if kind == "race_level":
      return {
        "kind": kind,
        "level": int(groups[0]),
        "race": groups[1],
        "count": int(groups[2]),
        "raw": cleaned,
      }
    if kind in {"archetype", "archetype_min"}:
      return {"kind": kind, "archetype": groups[0], "count": int(groups[1]), "raw": cleaned}
    if kind in {"race", "race_min"}:
      return {"kind": kind, "race": groups[0], "count": int(groups[1]), "raw": cleaned}
    if kind in {"any", "any_min"}:
      return {"kind": kind, "count": int(groups[0]), "raw": cleaned}
    if kind in {"ed_monster", "nonlink", "effect", "effect_min", "different_names"}:
      return {"kind": kind, "count": int(groups[0]), "raw": cleaned}
  return {"kind": "unknown", "count": 1, "raw": cleaned}


def material_line(card: dict) -> str:
  """取卡牌描述的第一行（Link/融合等怪兽的素材行）。"""
  lines = [ln.strip() for ln in card["desc"].splitlines() if ln.strip()]
  return lines[0] if lines else ""


def _main_monsters(deck: dict) -> list[dict]:
  return [c for c in deck["main"] if c["is_monster"]]


def match_material(gate: dict, deck: dict) -> list[dict]:
  """返回满足该素材条件的卡（含份数），只从主卡组与额外卡组里找。"""
  main = _main_monsters(deck)
  kind = gate.get("kind")
  if kind == "ns_max_atk":
    max_atk = gate["max_atk"]
    return [
      c
      for c in main
      if c["atk"] is not None and c["atk"] <= max_atk and not c["cannot_normal_summon"]
    ]
  if kind == "race_level":
    return [c for c in main if c["race"] == gate["race"] and (c["level"] or 0) <= gate["level"]]
  if kind in {"race", "race_min"}:
    return [c for c in main if c["race"] == gate["race"]]
  if kind in {"archetype", "archetype_min"}:
    target = gate["archetype"]
    return [c for c in main if target in c["name"] or target in c["archetypes"]]
  if kind == "nonlink":
    return list(main)
  if kind in {"effect", "effect_min"}:
    return [c for c in main if c["is_effect"]]
  if kind == "different_names":
    return list(main)
  if kind in {"any", "any_min"}:
    return list(main)
  if kind == "ed_monster":
    return [c for c in deck["extra"] if c["is_monster"]]
  return []


def satisfier_summary(cards: list[dict]) -> dict:
  total = sum(c["count"] for c in cards)
  return {
    "copies": total,
    "cards": [{"name": c["name"], "copies": c["count"]} for c in cards],
  }


# ---------------------------------------------------------------- 需求抽取 ---


def extract_triggers(card: dict) -> list[dict]:
  """找出一张卡文本里的全部「外部触发条件」。

  长句优先：「融合·连接怪兽特殊召唤的场合」本身就包含「连接怪兽特殊召唤的场合」
  这个子串，如果不去重，同一行会被算成两种不同的需求。
  """
  desc = card["desc"]
  found = []
  for needle, kind, meaning in TRIGGER_PATTERNS:
    start = desc.find(needle)
    while start >= 0:
      found.append(
        {
          "start": start,
          "end": start + len(needle),
          "kind": kind,
          "text": needle,
          "meaning": meaning,
        }
      )
      start = desc.find(needle, start + 1)

  kept = []
  for item in found:
    span = item["end"] - item["start"]
    covered = any(
      other is not item
      and other["start"] <= item["start"]
      and other["end"] >= item["end"]
      and (other["end"] - other["start"]) > span
      for other in found
    )
    if not covered:
      kept.append(item)

  triggers = []
  seen = set()
  for item in kept:
    key = (item["kind"], item["text"])
    if key in seen:
      continue
    seen.add(key)
    # 「这张卡被送去墓地／被破坏」通常是回收条款，不是展开起点
    window = desc[max(0, item["start"] - 8) : item["start"]]
    self_trigger = "这张卡" in window
    if self_trigger and item["kind"] in {"sent_to_gy", "destroyed"}:
      continue
    snippet = desc[max(0, item["start"] - 30) : item["end"] + 30].replace("\n", " ")
    triggers.append(
      {
        "kind": item["kind"],
        "text": item["text"],
        "meaning": item["meaning"],
        "snippet": snippet,
        "self_trigger": self_trigger,
        "weak": item["kind"] in WEAK_TRIGGER_KINDS,
      }
    )
  return triggers


def link_monsters(deck: dict) -> list[dict]:
  """额外卡组里的连接怪兽，按 Link 值从低到高（越便宜越优先）。"""
  links = [c for c in deck["extra"] if c["is_link"]]
  links.sort(key=lambda c: (c["level"] or 0, c["name"]))
  result = []
  for card in links:
    line = material_line(card)
    gate = parse_material(line)
    satisfiers = match_material(gate, deck)
    result.append(
      {
        "name": card["name"],
        "link_rating": card["level"],
        "material": line,
        "gate": gate,
        "satisfier": satisfier_summary(satisfiers),
      }
    )
  return result


def find_enablers(kind: str, triggeree: dict, deck: dict, links: list[dict]) -> list[dict]:
  """给定一种需求，返回卡组里能提供它的卡（附证据）。"""
  enablers = []
  if kind in LINK_TRIGGER_KINDS:
    for link in links:
      if link["satisfier"]["copies"] == 0:
        continue
      enablers.append(
        {
          "card": link["name"],
          "link_rating": link["link_rating"],
          "material": link["material"],
          "satisfier_copies": link["satisfier"]["copies"],
          "note": "{} 做连接召唤即可触发".format(link["name"]),
        }
      )
    return sorted(enablers, key=lambda e: (e["link_rating"] or 99, -e["satisfier_copies"]))

  if kind == "banished":
    for card in deck["main"] + deck["extra"]:
      if card["name"] == triggeree["name"] or "除外" not in card["desc"]:
        continue
      if "把" not in card["desc"] and "除外" not in card["desc"]:
        continue
      enablers.append(
        {
          "card": card["name"],
          "copies": card["count"],
          "note": "文本含「除外」，可能可以作为除外来源",
        }
      )
    return enablers

  if kind == "sent_to_gy":
    return [
      {"card": c["name"], "copies": c["count"], "note": "文本含「送去墓地」"}
      for c in deck["main"]
      if "送去墓地" in c["desc"] and c["name"] != triggeree["name"]
    ]

  if kind == "destroyed":
    return [
      {"card": c["name"], "copies": c["count"], "note": "文本含「破坏」"}
      for c in deck["main"]
      if "破坏" in c["desc"] and c["name"] != triggeree["name"]
    ]

  if kind in {"any_summon", "normal_special_summon"}:
    return [
      {"card": c["name"], "copies": c["count"], "note": "文本含「特殊召唤」"}
      for c in deck["main"]
      if "特殊召唤" in c["desc"] and c["name"] != triggeree["name"]
    ]

  return []


# -------------------------------------------------------------------- 扫描 ---


def scan(deck: dict) -> dict:
  links = link_monsters(deck)
  triggers = []
  pairs = []

  for card in deck["main"] + deck["extra"]:
    for trigger in extract_triggers(card):
      enablers = find_enablers(trigger["kind"], card, deck, links)
      triggers.append(
        {
          "card": card["name"],
          "copies": card["count"],
          "section": card["section"],
          "kind": trigger["kind"],
          "text": trigger["text"],
          "snippet": trigger["snippet"],
          "self_trigger": trigger["self_trigger"],
          "weak": trigger["weak"],
          "enabler_count": len(enablers),
          "enablers": enablers[:8],
        }
      )
      for enabler in enablers[:3]:
        pairs.append(
          {
            "trigger_card": card["name"],
            "enabler_card": enabler["card"],
            "kind": trigger["kind"],
            "evidence": enabler["note"],
          }
        )

  triggers.sort(key=lambda t: (t["weak"], t["section"] != "main", -t["copies"], t["card"]))
  return {
    "deck": {section: sum(c["count"] for c in cards) for section, cards in deck.items()},
    "link_monsters": links,
    "triggers": triggers,
    "candidate_pairs": pairs,
    "notes": [
      "本报告只做机械联结，不是结论：候选组合仍需按卡片文本逐条验证。",
      "CSV 输入不含 archetypes 字段，按卡名包含关系近似匹配；需要精确匹配请用 JSON 输入。",
    ],
  }


def render_human(report: dict, show_all: bool = False) -> str:
  lines = []
  deck = report["deck"]
  lines.append("卡组：主 {} / 额外 {} / 副 {}".format(deck["main"], deck["extra"], deck["side"]))
  lines.append("")
  lines.append("== 额外卡组连接怪兽（越靠前越便宜）==")
  for link in report["link_monsters"]:
    lines.append(
      "  L{} {:<22} 素材：{:<26} 可用牌 {} 张".format(
        link["link_rating"] or "?",
        link["name"],
        link["material"][:24],
        link["satisfier"]["copies"],
      )
    )
  lines.append("")
  lines.append("== 触发需求 ==")
  shown = [t for t in report["triggers"] if show_all or not t["weak"]]
  for trigger in shown:
    lines.append(
      "[{}] ×{}  ({} 种满足者)".format(trigger["card"], trigger["copies"], trigger["enabler_count"])
    )
    lines.append("  需求：{}（{}）".format(trigger["text"], trigger["kind"]))
    for enabler in trigger["enablers"][:4]:
      lines.append("    ← {}".format(enabler["card"]))
    if not trigger["enablers"]:
      lines.append("    ← （卡组内无满足者）")
  hidden = len(report["triggers"]) - len(shown)
  if hidden:
    lines.append("")
    lines.append(f"（另有 {hidden} 条弱提示已折叠，加 --all 查看）")
  return "\n".join(lines)


def main():
  parser = argparse.ArgumentParser(description="扫描卡组的二卡动点候选（需求 → 满足者）")
  parser.add_argument("deck", help="deck_raw.json 或 deck_raw.csv")
  parser.add_argument("--output", "-o", help="把 JSON 报告写入文件")
  parser.add_argument("--json", action="store_true", help="直接输出 JSON 而不是摘要")
  parser.add_argument("--all", action="store_true", help="摘要里也显示弱提示")
  args = parser.parse_args()

  deck = load_deck(args.deck)
  if not deck["main"]:
    print("错误：没有读到主卡组，请检查输入文件", file=sys.stderr)
    return 1

  report = scan(deck)
  if args.output:
    Path(args.output).write_text(
      json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
  if args.json:
    print(json.dumps(report, ensure_ascii=False, indent=2))
  else:
    print(render_human(report, show_all=args.all))
    if args.output:
      print(f"\nJSON 报告已写入 {args.output}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
