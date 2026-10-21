#!/usr/bin/env python3
"""M5d：按 combo_lines 的剧本驱动引擎，逐步验证每一步能不能执行。

前三个里程碑（m5a/m5b/m5c）各自硬编码了一两个动作。这里把它们收成一个通用执行器：

- 每一步读 `action` 和 `uses`，决定去**哪个消息**里找选项
  - `normal_summon` → `SELECT_IDLECMD.summon` 里找卡号
  - `link_summon`   → `SELECT_IDLECMD.spsummon`（额外卡组的怪兽从这里出来）
  - `activate` / `special_summon` → 依次试 `SELECT_EFFECTYN` / `SELECT_CHAIN` / `IDLECMD.activate`
- 找不到就**停在步骤 N**，把当时引擎给的全部选项打出来——这是最有用的诊断信息
- 与当前步骤无关的消息用「安全默认值」回应（放弃连锁 / 不进战阶），保证引擎不会卡死

用法::

    python m5d.py --dll build/ocgcore.dll --cdb cards.cdb --ydk deck.ydk \\
        --scripts scripts/ --analysis deck_analysis.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import messages as msg
from m5a import Session
from ocg_constants import (
  LOCATION_MZONE,
  LOCATION_SZONE,
  MSG_SELECT_CARD,
  MSG_SELECT_CHAIN,
  MSG_SELECT_EFFECTYN,
  MSG_SELECT_IDLECMD,
  MSG_SELECT_OPTION,
  MSG_SELECT_PLACE,
  MSG_SELECT_POSITION,
)


class Deck:
  """卡名 ↔ 卡号，以及主卡组/额外卡组的划分。"""

  def __init__(self, cdb: Path, ydk: Path):
    self.connection = sqlite3.connect(cdb)
    self.names: dict[int, str] = {}
    self.codes: dict[str, int] = {}
    # texts 表里同一个卡名可能有多个 id（异画/复刻指向原卡），
    # 取 datas.alias == 0 的那张正卡，否则会拿到 +1 的异画号，匹配全失败。
    for row in self.connection.execute(
      "SELECT t.id, t.name, d.alias FROM texts t LEFT JOIN datas d ON d.id = t.id"
    ):
      card_id, name, alias = row
      self.names.setdefault(card_id, name)
      if name not in self.codes or not alias:
        self.codes[name] = card_id if not alias else self.codes.get(name, card_id)
    from probe import read_ydk

    deck = read_ydk(ydk)
    self.main = set(deck["main"])
    self.extra = set(deck["extra"])

  def code(self, name: str) -> int:
    return self.codes.get(name, 0)

  def summon_target(self, text: str, *, extra: bool) -> int | None:
    """从自然语言里找出召唤的是哪张卡（优先额外卡组/主卡组对应区）。"""
    pool = self.extra if extra else self.main
    for code in pool:
      name = self.names.get(code, "")
      if name and name in text:
        return code
    return None


def expected_codes(step: dict, deck: Deck) -> list[int]:
  """这一步要用到哪些卡。`uses` 优先，没有的话从 `act` 里找召唤目标。"""
  codes = [deck.code(use["card"]) for use in step.get("uses") or []]
  codes = [code for code in codes if code]
  if codes:
    return codes
  action = step.get("action")
  text = step.get("act", "")
  if action == "normal_summon":
    target = deck.summon_target(text, extra=False)
  elif action == "link_summon":
    target = deck.summon_target(text, extra=True)
  else:
    target = None
  return [target] if target else []


def describe_idle(idle: dict) -> str:
  parts = []
  for key in ("summon", "spsummon", "activate"):
    if idle.get(key):
      parts.append(f"{key}={[entry['code'] for entry in idle[key]]}")
  return " ".join(parts) or "（无动作）"


def run(args) -> int:
  deck = Deck(args.cdb, args.ydk)
  analysis = json.loads(args.analysis.read_text(encoding="utf-8-sig"))
  line = next(
    (item for item in analysis["combo_lines"] if item["name"].startswith(args.line)),
    analysis["combo_lines"][0],
  )
  steps = line["steps"]
  print(f"剧本：{line['name']}（{len(steps)} 步）\n")

  session = Session(args, args.seed)
  index = 0
  idle_seen = 0
  try:
    for _ in range(2000):
      status, buffer = session.step()
      for message in msg.split(buffer):
        if message.type == MSG_SELECT_IDLECMD:
          idle = msg.decode_idlecmd(message)
          idle_seen += 1
          while index < len(steps) and steps[index].get("action") == "resolve":
            index += 1
          if index >= len(steps):
            print(f"[M5d] 通过：{len(steps)} 步全部执行完")
            return 0
          step = steps[index]
          action = step.get("action")
          codes = expected_codes(step, deck)

          chosen = None
          if action == "normal_summon":
            chosen = next(
              ((msg.IDLE_SUMMON, i) for i, e in enumerate(idle["summon"]) if e["code"] in codes),
              None,
            )
          elif action == "link_summon":
            chosen = next(
              (
                (msg.IDLE_SPSUMMON, i) for i, e in enumerate(idle["spsummon"]) if e["code"] in codes
              ),
              None,
            )
          elif action == "activate":
            chosen = next(
              (
                (msg.IDLE_ACTIVATE, i) for i, e in enumerate(idle["activate"]) if e["code"] in codes
              ),
              None,
            )

          if chosen is None:
            print(f"[M5d] 第 {index + 1} 步不可行：{step['act'][:40]}")
            print(f"       期望卡号 {codes}，引擎给的是 {describe_idle(idle)}")
            return 1
          session.respond(msg.encode_idlecmd_response(*chosen))
          print(f"  {index + 1:2d}. ✓ {step['act'][:48]}")
          index += 1

        elif message.type == MSG_SELECT_EFFECTYN:
          choice = msg.decode_effectyn(message)
          step = steps[index] if index < len(steps) else None
          if step and choice["code"] in expected_codes(step, deck):
            session.respond(msg.encode_yes_no(True))
            print(f"  {index + 1:2d}. ✓ {step['act'][:48]}（EFFECTYN）")
            index += 1
          else:
            session.respond(msg.encode_yes_no(False))

        elif message.type == MSG_SELECT_CHAIN:
          chain = msg.decode_chain(message)
          step = steps[index] if index < len(steps) else None
          target = None
          if step:
            print(
              f"        [连锁] 步骤 {index + 1} 期望 "
              f"{expected_codes(step, deck)}，窗口 {[e['code'] for e in chain['chains']]}"
              f" forced={chain['forced']}"
            )
          if step:
            codes = expected_codes(step, deck)
            target = next((i for i, e in enumerate(chain["chains"]) if e["code"] in codes), None)
          if target is not None:
            session.respond(msg.encode_chain_response(target))
            print(f"  {index + 1:2d}. ✓ {steps[index]['act'][:48]}")
            index += 1
          elif chain["forced"]:
            session.respond(msg.encode_chain_response(0))
          else:
            session.respond(msg.encode_chain_response(-1))

        elif message.type == MSG_SELECT_CARD:
          selection = msg.decode_select_card(message)
          step = steps[index] if index < len(steps) else None
          codes = expected_codes(step, deck) if step else []
          preferred = next(
            (i for i, card in enumerate(selection["cards"]) if card["code"] in codes), None
          )
          if preferred is None and step:
            # cost 这类选择不在 uses 里，但步骤文本会写「除外白兔」——
            # 按文本里出现的卡名挑，比盲选第一个可靠
            text = step.get("act", "")
            preferred = next(
              (
                i
                for i, card in enumerate(selection["cards"])
                if deck.names.get(card["code"], "") in text
              ),
              None,
            )
          if preferred is not None:
            chosen = [preferred]
          else:
            take = max(selection["min"], 1)
            chosen = list(range(min(take, len(selection["cards"]))))
          session.respond(msg.encode_card_response(chosen))

        elif message.type == MSG_SELECT_PLACE:
          place = msg.decode_place(message)
          zones = msg.zones_from_flag(place["flag"])
          mzones = [zone for zone in zones if zone < 7]
          szones = [zone for zone in zones if zone >= 8]
          if mzones:
            session.respond(msg.encode_place_response(place["player"], LOCATION_MZONE, mzones[0]))
          elif szones:
            session.respond(
              msg.encode_place_response(place["player"], LOCATION_SZONE, szones[0] - 8)
            )
          else:
            return 1

        elif message.type == MSG_SELECT_POSITION:
          position = msg.decode_position(message)
          session.respond(msg.encode_position(0x1 if position["positions"] & 0x1 else 0x4))

        elif message.type == MSG_SELECT_OPTION:
          session.respond(bytes([0]))

      if status == 0:
        print(f"[M5d] 对局结束（走到第 {index + 1} 步）")
        return 1
    return 1
  finally:
    session.close()


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="M5d：按剧本驱动引擎。")
  parser.add_argument("--dll", type=Path, required=True)
  parser.add_argument("--cdb", type=Path, required=True)
  parser.add_argument("--ydk", type=Path, required=True)
  parser.add_argument("--scripts", type=Path, required=True)
  parser.add_argument("--analysis", type=Path, required=True)
  parser.add_argument("--line", default="白兔线")
  parser.add_argument("--seed", type=int, default=8)
  return run(parser.parse_args(argv))


if __name__ == "__main__":
  raise SystemExit(main())
