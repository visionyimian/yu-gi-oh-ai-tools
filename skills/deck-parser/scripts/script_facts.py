#!/usr/bin/env python3
"""从 ygopro-scripts 的卡脚本里读出效果的硬事实。

YGOCore 用 Lua 描述每张卡的效果，文件名是 ``c<passcode>.lua``。脚本里的声明比
中文效果文本精确，正好覆盖 ocg-rules 清单里的几条判据：

===================  ==========================  ==========
Lua 声明              含义                          清单条目
===================  ==========================  ==========
SetCountLimit(1, id) 卡名限定（一场决斗/回合一次）      C1
SetCountLimit(1)     卡限定（这张卡一次）               C1
（无 SetCountLimit）   无次数限制                       C1
EFFECT_FLAG_DELAY    不会错过时点（等价「場合」）         C2
EFFECT_TYPE_*        起动 / 诱发 / 诱发即时             C3
SetCost(...)         该段是 cost                      C5
EFFECT_FLAG_CARD_TARGET  取对象                        C6
===================  ==========================  ==========

用法::

    python script_facts.py --ydk deck.ydk -o facts.json
    python script_facts.py --ids 69272449 96676583
    python script_facts.py --ydk deck.ydk --cache ./scripts --offline
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_URLS = (
  "https://raw.githubusercontent.com/mycard/ygopro-scripts/master",
  "https://raw.githubusercontent.com/Fluorohydride/ygopro-scripts/master",
)

CREATE_RE = re.compile(r"^\s*local\s+(\w+)\s*=\s*Effect\.CreateEffect\s*\(")
CLONE_RE = re.compile(r"^\s*local\s+(\w+)\s*=\s*(\w+):Clone\s*\(\s*\)")
SETTER_RE = re.compile(r"^\s*(\w+)\s*:\s*Set(\w+)\s*\((.*)\)\s*$")
# 两种命名风格：新卡用 s.initial_effect，老卡用 c<passcode>.initial_effect
ENTRY_RE = re.compile(r"^function\s+\w+\.initial_effect\s*\(")
RESTRICTION_RE = re.compile(r"EFFECT_CANNOT_[A-Z_]+")
FLAG_RE = re.compile(r"Duel\.GetFlagEffect\s*\(\s*([^)]*?)\s*\)\s*(<=|>=|==|<|>)\s*(\d+)")
AUX_RE = re.compile(r"aux\.(Enable\w+)")

KIND_ORDER = (
  ("EFFECT_TYPE_IGNITION", "ignition"),
  ("EFFECT_TYPE_QUICK_O", "quick_optional"),
  ("EFFECT_TYPE_QUICK_F", "quick_mandatory"),
  ("EFFECT_TYPE_TRIGGER_O", "trigger_optional"),
  ("EFFECT_TYPE_TRIGGER_F", "trigger_mandatory"),
  ("EFFECT_TYPE_ACTIVATE", "activation"),
  ("EFFECT_TYPE_CONTINUOUS", "continuous"),
)

OPT_LABELS = {"card_name": "card_name_once", "card": "once_per_turn", "none": "unlimited"}


def read_ydk_ids(path: Path) -> list[int]:
  """按出现顺序收集 .ydk 里的卡号（去重）。"""
  ids: list[int] = []
  seen: set[int] = set()
  for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith(("#", "!")):
      continue
    if not line.isdigit():
      continue
    passcode = int(line)
    if passcode not in seen:
      seen.add(passcode)
      ids.append(passcode)
  return ids


def fetch_script(passcode: int, cache: Path, urls: tuple[str, ...], offline: bool) -> str | None:
  """优先读缓存；缓存没有且允许联网时按顺序下载。"""
  target = cache / f"c{passcode}.lua"
  if target.is_file():
    return target.read_text(encoding="utf-8", errors="replace")
  if offline:
    return None

  for base in urls:
    try:
      with urllib.request.urlopen(f"{base}/c{passcode}.lua", timeout=30) as response:
        text = response.read().decode("utf-8", errors="replace")
    except OSError:
      # URLError/HTTPError 都是 OSError 的子类，换下一个源
      continue
    cache.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return text
  return None


def initial_effect_body(text: str) -> list[str]:
  """截取 <prefix>.initial_effect(c) ... end 这一段。"""
  lines = text.splitlines()
  start = None
  for index, line in enumerate(lines):
    if ENTRY_RE.match(line):
      start = index + 1
      break
  if start is None:
    return []

  body: list[str] = []
  for line in lines[start:]:
    if line.startswith("end"):
      break
    body.append(line)
  return body


def split_args(raw: str) -> list[str]:
  return [part.strip() for part in raw.split(",") if part.strip()]


def parse_card(text: str) -> dict:
  """把一张卡的脚本解析成效果列表。"""
  effects: list[dict] = []
  by_var: dict[str, dict] = {}

  for line in initial_effect_body(text):
    code = line.split("--")[0].rstrip()
    if not code:
      continue

    created = CREATE_RE.match(code)
    if created:
      effect = {"index": len(effects) + 1, "types": [], "flags": [], "event": None}
      by_var[created.group(1)] = effect
      effects.append(effect)
      continue

    cloned = CLONE_RE.match(code)
    if cloned:
      source = by_var.get(cloned.group(2))
      if source is not None:
        effect = json.loads(json.dumps(source))
        effect["index"] = len(effects) + 1
        effect["cloned_from"] = source["index"]
        by_var[cloned.group(1)] = effect
        effects.append(effect)
      continue

    setter = SETTER_RE.match(code)
    if not setter:
      continue
    var, name, raw_args = setter.groups()
    effect = by_var.get(var)
    if effect is None:
      continue

    args = split_args(raw_args)
    if name == "Type":
      effect["types"] = [token for token in raw_args.split("+") if token.strip()]
    elif name == "Property":
      effect["flags"] = [token for token in raw_args.split("+") if token.strip()]
    elif name == "Code":
      effect["event"] = raw_args.strip()
    elif name == "CountLimit":
      effect["count_limit"] = int(args[0]) if args and args[0].isdigit() else 1
      effect["count_limit_key"] = args[1] if len(args) > 1 else None
    elif name == "Cost":
      effect["cost"] = raw_args.strip()
    elif name == "Category":
      effect["categories"] = [token for token in raw_args.split("+") if token.strip()]

  for effect in effects:
    types = effect.get("types", [])
    flags = effect.get("flags", [])
    kind = next((kind for token, kind in KIND_ORDER if token in types), "other")
    # 只标了 SINGLE/FIELD、没有触发类型的，属于持续适用（永续/无分类）效果
    if kind == "other" and {"EFFECT_TYPE_SINGLE", "EFFECT_TYPE_FIELD"} & set(types):
      kind = "continuous"
    effect["kind"] = kind
    if "count_limit_key" in effect:
      effect["opt"] = "card_name" if effect["count_limit_key"] else "card"
    elif "count_limit" in effect:
      effect["opt"] = "card"
    else:
      effect["opt"] = "none"
    effect["no_miss_timing"] = "EFFECT_FLAG_DELAY" in flags
    effect["targets"] = "EFFECT_FLAG_CARD_TARGET" in flags
    effect["has_cost"] = "cost" in effect

  direct = {
    effect["event"] for effect in effects if (effect.get("event") or "").startswith("EFFECT_CANNOT")
  }
  # 有些限制是在效果结算时才挂上去的（写在 helper 函数里），这里单独列出来
  indirect = set(RESTRICTION_RE.findall(text)) - direct

  # 次数限制不一定用 SetCountLimit 表达：有的卡用 GetFlagEffect 计数，
  # 有的靠 aux.Enable*Check 之类的共享 helper。这种情况下不能判成「无限制」，
  # 但也不该由脚本猜语义——把证据原样列出来，交给 agent 复核。
  flag_checks = [
    f"Duel.GetFlagEffect({expr}) {op} {value}" for expr, op, value in FLAG_RE.findall(text)
  ]
  aux_helpers = sorted(set(AUX_RE.findall(text)))
  custom_opt = bool(flag_checks) or bool(aux_helpers)

  return {
    "effects": effects,
    "restrictions": sorted(direct),
    "indirect_restrictions": sorted(indirect),
    "custom_opt": custom_opt,
    "custom_evidence": {"flag_checks": flag_checks, "aux_helpers": aux_helpers},
  }


def summarize_opt(facts: dict) -> str:
  """把每张卡的效果次数限制汇总成一个值，用于和 deck_parsed 的枚举对照。

  返回 ``custom`` 表示「脚本里没有 SetCountLimit，但用了 flag/aux 计数」——
  这种情况不能当成无限制，需要人工确认。
  """
  active = [effect for effect in facts["effects"] if effect.get("opt") != "none"]
  if not active:
    return "custom" if facts.get("custom_opt") else "unlimited"
  kinds = {effect["opt"] for effect in active}
  if kinds == {"card_name"}:
    return "card_name_once"
  if kinds == {"card"}:
    return "once_per_turn"
  return "mixed"


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="解析 ygopro-scripts，输出卡片效果的硬事实。")
  source = parser.add_mutually_exclusive_group(required=True)
  source.add_argument("--ydk", type=Path, help="从 .ydk 读取卡号")
  source.add_argument("--ids", nargs="+", type=int, help="直接给卡号")
  parser.add_argument("--cache", type=Path, default=Path(".cache/ygopro-scripts"))
  parser.add_argument("--offline", action="store_true", help="只用缓存，不联网")
  parser.add_argument("--url", action="append", help="覆盖下载地址，可重复")
  parser.add_argument("-o", "--out", type=Path, help="输出文件，默认打印到标准输出")
  args = parser.parse_args(argv)

  ids = read_ydk_ids(args.ydk) if args.ydk else args.ids
  urls = tuple(args.url) if args.url else DEFAULT_URLS

  cards: list[dict] = []
  missing: list[int] = []
  for passcode in ids:
    text = fetch_script(passcode, args.cache, urls, args.offline)
    if text is None:
      missing.append(passcode)
      continue
    facts = parse_card(text)
    summary = summarize_opt(facts)
    card = {
      "id": passcode,
      "opt": summary,
      "restrictions": facts["restrictions"],
      "indirect_restrictions": facts["indirect_restrictions"],
      "effects": facts["effects"],
    }
    if summary == "custom":
      card["custom_evidence"] = facts["custom_evidence"]
    cards.append(card)

  payload = {"cards": cards, "missing": missing}
  body = json.dumps(payload, ensure_ascii=False, indent=2)
  if args.out:
    args.out.write_text(body, encoding="utf-8")
    print(f"已写入 {args.out}：{len(cards)} 张卡，{len(missing)} 张缺失")
  else:
    sys.stdout.write(body + "\n")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
