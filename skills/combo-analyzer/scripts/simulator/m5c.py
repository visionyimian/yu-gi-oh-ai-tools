#!/usr/bin/env python3
"""M5c：从主阶段动作列表里发动 TB-11，并把「除外白兔 → 特殊召唤睡鼠」走完。

M5b 只走了「诱发效果」那条路（SELECT_EFFECTYN）。发动已经盖在场上的陷阱走的是
另一条路：`MSG_SELECT_IDLECMD` 的 `activate` 列表。

这一步要验证：
1. 能在 `activate` 列表里按卡号认出 TB-11
2. TB-11 的 cost（除外自己场上的码丽丝）会以 `MSG_SELECT_CARD` 的形式问出来
3. 特殊召唤的目标选择也能回应

用法::

    python m5c.py --dll build/ocgcore.dll --cdb cards.cdb --ydk deck.ydk --scripts scripts/
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import messages as msg
from m5a import BAI_TU, Session
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
  MSG_SET,
  MSG_SPSUMMONED,
)

TB11 = 57111661  # 码丽丝<代码>TB-11


def card_code(cdb: Path, name: str) -> int:
  connection = sqlite3.connect(cdb)
  try:
    row = connection.execute("SELECT id FROM texts WHERE name = ?", (name,)).fetchone()
    return row[0] if row else 0
  finally:
    connection.close()


def attempt(args, seed: int, verbose: bool) -> str:
  session = Session(args, seed)
  trace: list[str] = []
  stage = "summon"  # summon -> effect -> activate_tb11 -> done
  try:
    for _ in range(600):
      status, buffer = session.step()
      for message in msg.split(buffer):
        if verbose:
          trace.append(message.name)

        if message.type == MSG_SELECT_IDLECMD:
          idle = msg.decode_idlecmd(message)
          if stage == "summon":
            index = next((i for i, e in enumerate(idle["summon"]) if e["code"] == BAI_TU), None)
            if index is None:
              return "no_bai_tu"
            session.respond(msg.encode_idlecmd_response(msg.IDLE_SUMMON, index))
            stage = "effect"
            trace.append("-> 通召白兔")
          elif stage == "activate_tb11":
            index = next((i for i, e in enumerate(idle["activate"]) if e["code"] == TB11), None)
            if index is None:
              offered = [e["code"] for e in idle["activate"]]
              trace.append(f"-> TB-11 不在可发动列表 {offered}")
              return "failed"
            session.respond(msg.encode_idlecmd_response(msg.IDLE_ACTIVATE, index))
            stage = "after_tb11"
            trace.append(f"-> 发动 TB-11（下标 {index}）")
          else:
            trace.append(f"-> 进战阶前结束（stage={stage}）")
            return "failed"

        elif message.type == MSG_SELECT_EFFECTYN:
          choice = msg.decode_effectyn(message)
          if choice["code"] == BAI_TU and stage == "effect":
            session.respond(msg.encode_yes_no(True))
            stage = "activate_tb11"
            trace.append("-> 发动白兔①（盖 TB-11）")
          else:
            session.respond(msg.encode_yes_no(False))

        elif message.type == MSG_SELECT_CHAIN:
          chain = msg.decode_chain(message)
          target = next((i for i, e in enumerate(chain["chains"]) if e["code"] == BAI_TU), None)
          if target is not None and stage == "effect":
            session.respond(msg.encode_chain_response(target))
            stage = "activate_tb11"
            trace.append("-> 连锁里发动白兔①")
          elif chain["forced"]:
            session.respond(msg.encode_chain_response(0))
          else:
            session.respond(msg.encode_chain_response(-1))

        elif message.type == MSG_SELECT_CARD:
          selection = msg.decode_select_card(message)
          codes = [card["code"] for card in selection["cards"]]
          # 白兔① 要从卡组里盖「指定的那张陷阱」——按卡号选，不能取第一个
          preferred = next(
            (i for i, card in enumerate(selection["cards"]) if card["code"] in (TB11, BAI_TU)),
            None,
          )
          if preferred is not None:
            chosen = [preferred]
          else:
            take = max(selection["min"], 1)
            chosen = list(range(min(take, len(codes))))
          session.respond(msg.encode_card_response(chosen))
          trace.append(f"-> 选卡 {chosen}（候选 {codes}）")

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
            return "failed"
          trace.append(f"-> 放到区域（{zones[:3]}）")

        elif message.type == MSG_SELECT_POSITION:
          position = msg.decode_position(message)
          # 回应是位置位而不是下标：能表攻就表攻，否则表守
          value = 0x1 if position["positions"] & 0x1 else 0x4
          session.respond(msg.encode_position(value))
          trace.append(f"-> 表示形式 0x{value:x}（可选 0x{position['positions']:x}）")

        elif message.type == MSG_SELECT_OPTION:
          session.respond(bytes([0]))
          trace.append("-> 选项 0")

        elif message.type == MSG_SET:
          trace.append("   [盖放]")

        elif message.type == MSG_SPSUMMONED:
          if verbose:
            trace.append("   [特殊召唤成功]")
          if stage == "after_tb11":
            return "ok"

      if status == 0:
        return "failed"
    return "failed"
  finally:
    session.close()
    if verbose:
      print(f"  seed {seed}: {' → '.join(trace)}")


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="M5c：发动 TB-11 并特殊召唤睡鼠。")
  parser.add_argument("--dll", type=Path, required=True)
  parser.add_argument("--cdb", type=Path, required=True)
  parser.add_argument("--ydk", type=Path, required=True)
  parser.add_argument("--scripts", type=Path, required=True)
  parser.add_argument("--seed", type=int, default=8)
  parser.add_argument("-v", "--verbose", action="store_true")
  args = parser.parse_args(argv)

  result = attempt(args, args.seed, args.verbose)
  if result == "ok":
    print(f"[M5c] 通过：seed={args.seed}，TB-11 发动并特殊召唤成功")
    return 0
  print(f"[M5c] 失败（{result}）")
  return 1


if __name__ == "__main__":
  raise SystemExit(main())
