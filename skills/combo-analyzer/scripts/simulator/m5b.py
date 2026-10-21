#!/usr/bin/env python3
"""M5b：在引擎的连锁窗口里选中「白兔①」并发动的，而不是干等。

白兔① 是「这张卡召唤·特殊召唤的场合才能发动」——**诱发效果**，所以它不会出现在
`MSG_SELECT_IDLECMD` 的动作列表里，而是在 `MSG_SELECT_CHAIN` 的连锁选项中。
这一步要做的就是在连锁窗口里按 `code` 认出它，回一个下标。

顺带把「不想发动」的连锁窗口用 -1 明确放弃（forced 的窗口不能放弃，必须选 0）。

用法::

    python m5b.py --dll build/ocgcore.dll --cdb cards.cdb --ydk deck.ydk --scripts scripts/
"""

from __future__ import annotations

import argparse
from pathlib import Path

import messages as msg
from m5a import BAI_TU, Session
from ocg_constants import (
  LOCATION_MZONE,
  LOCATION_SZONE,
  MSG_CHAIN_SOLVED,
  MSG_CHAINED,
  MSG_CHAINING,
  MSG_SELECT_CARD,
  MSG_SELECT_CHAIN,
  MSG_SELECT_EFFECTYN,
  MSG_SELECT_IDLECMD,
  MSG_SELECT_PLACE,
  MSG_SET,
)


def attempt(args, seed: int, verbose: bool) -> str:
  """返回值：ok / no_bai_tu / failed。"""
  session = Session(args, seed)
  trace: list[str] = []
  chose_effect = False
  try:
    for _ in range(400):
      status, buffer = session.step()
      for message in msg.split(buffer):
        if verbose:
          trace.append(message.name)

        if message.type == MSG_SELECT_IDLECMD:
          idle = msg.decode_idlecmd(message)
          index = next(
            (i for i, entry in enumerate(idle["summon"]) if entry["code"] == BAI_TU), None
          )
          if index is None:
            return "no_bai_tu"
          session.respond(msg.encode_idlecmd_response(msg.IDLE_SUMMON, index))
          trace.append("-> 通召白兔")

        elif message.type == MSG_SELECT_PLACE:
          place = msg.decode_place(message)
          zones = msg.zones_from_flag(place["flag"])
          mzones = [zone for zone in zones if zone < 7]
          szones = [zone for zone in zones if zone >= 8]
          if mzones:
            session.respond(msg.encode_place_response(place["player"], LOCATION_MZONE, mzones[0]))
            trace.append(f"-> 放到怪兽区 {mzones[0]}")
          elif szones:
            session.respond(
              msg.encode_place_response(place["player"], LOCATION_SZONE, szones[0] - 8)
            )
            trace.append(f"-> 放到魔陷区 {szones[0] - 8}")
          else:
            return "failed"

        elif message.type == MSG_SELECT_CHAIN:
          chain = msg.decode_chain(message)
          codes = [entry["code"] for entry in chain["chains"]]
          trace.append(f"   [连锁窗口 code={codes} forced={chain['forced']}]")
          target = next(
            (
              i
              for i, entry in enumerate(chain["chains"])
              if entry["code"] == BAI_TU and not chose_effect
            ),
            None,
          )
          if target is not None:
            session.respond(msg.encode_chain_response(target))
            chose_effect = True
            trace.append(f"-> 发动白兔①（连锁下标 {target}）")
          elif chain["forced"]:
            session.respond(msg.encode_chain_response(0))
            trace.append("-> 被迫选连锁 0")
          else:
            session.respond(msg.encode_chain_response(-1))
            trace.append("-> 放弃连锁")

        elif message.type == MSG_SELECT_EFFECTYN:
          # 「要发动这个效果吗？」——白兔① 就走这个窗口
          choice = msg.decode_effectyn(message)
          if choice["code"] == BAI_TU and not chose_effect:
            session.respond(msg.encode_yes_no(True))
            chose_effect = True
            trace.append("-> 发动白兔①（EFFECTYN 是）")
          else:
            session.respond(msg.encode_yes_no(False))
            trace.append(f"-> 不发动 {choice['code']}")

        elif message.type == MSG_SELECT_CARD:
          # 白兔① 结算时「从卡组选 1 张码丽丝陷阱盖放」
          selection = msg.decode_select_card(message)
          take = max(selection["min"], 1)
          chosen = list(range(min(take, len(selection["cards"]))))
          session.respond(msg.encode_card_response(chosen))
          codes = [card["code"] for card in selection["cards"]]
          trace.append(f"-> 选卡 {chosen}（候选 {codes}）")

        elif message.type == MSG_CHAINING:
          trace.append("   [连锁开始]")
        elif message.type == MSG_CHAINED:
          trace.append("   [连锁成立]")
        elif message.type == MSG_CHAIN_SOLVED:
          trace.append("   [连锁结算]")
          if chose_effect:
            return "ok"
        elif message.type == MSG_SET:
          trace.append("   [盖放]")

      if status == 2 and not buffer:
        break
      if status == 0:
        return "failed"
    return "failed"
  finally:
    session.close()
    if verbose:
      text = " → ".join(trace)
      print(f"  seed {seed}: {text}")


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="M5b：在连锁窗口里发动白兔①。")
  parser.add_argument("--dll", type=Path, required=True)
  parser.add_argument("--cdb", type=Path, required=True)
  parser.add_argument("--ydk", type=Path, required=True)
  parser.add_argument("--scripts", type=Path, required=True)
  parser.add_argument("--seed", type=int)
  parser.add_argument("-v", "--verbose", action="store_true")
  args = parser.parse_args(argv)

  seeds = [args.seed] if args.seed else [8, 13, 15, 19, 24, 25, 26, 27, 28, 30]
  for seed in seeds:
    result = attempt(args, seed, args.verbose)
    if result == "ok":
      print(f"[M5b] 通过：seed={seed}，白兔① 在连锁窗口里发动并结算")
      return 0
  print("[M5b] 失败")
  return 1


if __name__ == "__main__":
  raise SystemExit(main())
