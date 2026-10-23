#!/usr/bin/env python3
"""M5a：让引擎接受「通常召唤码丽丝<兵卒>白兔」这一个动作。

M4 只是**读**消息，这里要**构造回应**并让引擎照做。成功的话会看到
MSG_SUMMONING / MSG_SUMMONED，说明「读消息 → 选选项 → 回包」的闭环通了。

洗牌是随机的，所以先换种子直到白兔上手，再做那一次通召——这样既验证了机制，
又不用为了凑手牌去关掉洗牌。

用法::

    python m5a.py --dll build/ocgcore.dll --cdb cards.cdb --ydk deck.ydk --scripts scripts/
"""

from __future__ import annotations

import argparse
import ctypes
import random
from pathlib import Path

import messages as msg
import ocgcore
from ocg_constants import (
  DUEL_MODE_MR5,
  LOCATION_MZONE,
  LOCATION_SZONE,
  MSG_SELECT_IDLECMD,
  MSG_SELECT_PLACE,
  MSG_SUMMONED,
  MSG_SUMMONING,
)
from probe import COMPAT_SCRIPT, CardTable, make_card_reader, read_ydk

BAI_TU = 69272449  # 码丽丝<兵卒>白兔
DECK_LOC = 1
EXTRA_LOC = 0x40


class Session:
  """一次对局的完整生命周期，便于换种子重开。"""

  def __init__(self, args, seed: int):
    self.core = ocgcore.Core(args.dll)
    self.table = CardTable(args.cdb)
    self.logs: list[str] = []

    def script_reader(payload, duel, name):
      filename = name.decode("utf-8", "replace")
      path = args.scripts / filename
      if not path.is_file():
        return 0
      data = path.read_bytes()
      return self.core.lib.OCG_LoadScript(duel, data, len(data), filename.encode())

    def log_handler(payload, text, kind):
      self.logs.append(text.decode("utf-8", "replace"))

    options = self.core.make_options(
      make_card_reader(self.table, []),
      script_reader,
      log_handler,
      seed=(seed, seed, seed, seed),
      # 规则必须给对：flags=0 等于「没有额外怪兽区」，那样朝下的箭头全部落空，
      # 小男巫这类「指向的区域」效果永远不触发，连接召唤也只能站主要怪兽区。
      # 录像头里的 masterRule 是 6（MDPro3 的 MR5），所以这里用 DUEL_MODE_MR5。
      flags=DUEL_MODE_MR5,
    )
    status, duel = self.core.create_duel(options)
    if duel is None:
      raise RuntimeError(f"CreateDuel 失败: {status}")
    self.duel = duel

    for name in ("constant.lua", "utility.lua", "procedure.lua"):
      data = (args.scripts / name).read_bytes()
      self.core.lib.OCG_LoadScript(duel, data, len(data), name.encode())
    # 兼容层：补齐卡脚本要用、本版引擎没注册的判定函数（没有它就没有连接召唤）
    if COMPAT_SCRIPT.is_file():
      data = COMPAT_SCRIPT.read_bytes()
      self.core.lib.OCG_LoadScript(duel, data, len(data), COMPAT_SCRIPT.name.encode())

    # 引擎自己**不洗牌**：Startup 直接从牌堆尾部抽牌，所以顺序就是我们插入的顺序。
    # 洗牌是客户端职责——这里用种子固定，保证可复现。
    deck = read_ydk(args.ydk)
    main = deck["main"][:]
    random.Random(seed).shuffle(main)
    # 对手默认用同一套牌；但「邻家割草」是按双方卡组张数的**差**削牌的，
    # 双方都 60 张时会削 0 张，等于这张卡在模拟器里永远不生效。
    # 所以割草变体要显式给对手一套 40 张的牌（--opponent-ydk）。
    opponent_path = getattr(args, "opponent_ydk", None)
    if opponent_path:
      opponent = read_ydk(opponent_path)
      opponent_main = opponent["main"][:]
      random.Random(seed ^ 0x5A5A).shuffle(opponent_main)
      decks = {
        0: {"main": main, "extra": deck["extra"]},
        1: {"main": opponent_main, "extra": opponent["extra"]},
      }
    else:
      decks = {0: {"main": main, "extra": deck["extra"]}, 1: {"main": main, "extra": deck["extra"]}}
    for team in (0, 1):
      for section, codes in (("main", decks[team]["main"]), ("extra", decks[team]["extra"])):
        loc = DECK_LOC if section == "main" else EXTRA_LOC
        for seq, code in enumerate(codes):
          info = ocgcore.NewCardInfo(
            team=team, duelist=0, code=code, con=team, loc=loc, seq=seq, pos=0
          )
          self.core.lib.OCG_DuelNewCard(duel, ctypes.byref(info))
    self.core.lib.OCG_StartDuel(duel)

  def step(self) -> tuple[int, bytes]:
    status = self.core.lib.OCG_DuelProcess(self.duel)
    length = ctypes.c_uint32(0)
    pointer = self.core.lib.OCG_DuelGetMessage(self.duel, ctypes.byref(length))
    buffer = ctypes.string_at(pointer, length.value) if pointer else b""
    return status, buffer

  def respond(self, data: bytes) -> None:
    self.core.lib.OCG_DuelSetResponse(self.duel, data, len(data))

  def close(self) -> None:
    self.core.destroy_duel(self.duel)


def attempt(args, seed: int, verbose: bool) -> str:
  """返回值：ok / no_bai_tu / failed。"""
  session = Session(args, seed)
  trace: list[str] = []
  try:
    for _ in range(300):
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
            if verbose:
              print(f"  seed {seed}: 手上没有白兔（可通召 {len(idle['summon'])} 张）")
            return "no_bai_tu"
          session.respond(msg.encode_idlecmd_response(msg.IDLE_SUMMON, index))
          trace.append(f"-> 通召白兔（下标 {index}）")

        elif message.type == MSG_SELECT_PLACE:
          # 通召之后引擎问「放到哪个格子」：挑第一个可用的怪兽区
          place = msg.decode_place(message)
          zones = msg.zones_from_flag(place["flag"])
          mzones = [zone for zone in zones if zone < 7]
          zone = mzones[0] if mzones else zones[0]
          location = LOCATION_MZONE if zone < 7 else LOCATION_SZONE
          session.respond(msg.encode_place_response(place["player"], location, zone))
          trace.append(f"-> 放到区域 {zone}（flag={place['flag']:#x}, count={place['count']}）")

        elif message.type in (MSG_SUMMONING, MSG_SUMMONED):
          return "ok"

      if status == ocgcore.DUEL_END:
        return "failed"
    return "failed"
  finally:
    session.close()
    if verbose and trace:
      print(f"  seed {seed} 轨迹: {' → '.join(trace)}")


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="M5a：验证通召动作能被引擎接受。")
  parser.add_argument("--dll", type=Path, required=True)
  parser.add_argument("--cdb", type=Path, required=True)
  parser.add_argument("--ydk", type=Path, required=True)
  parser.add_argument("--scripts", type=Path, required=True)
  parser.add_argument("--seed", type=int, help="指定种子（默认自动找白兔上手的那一个）")
  parser.add_argument("-v", "--verbose", action="store_true")
  args = parser.parse_args(argv)

  seeds = [args.seed] if args.seed else list(range(1, 41))
  for seed in seeds:
    result = attempt(args, seed, args.verbose)
    if result == "ok":
      print(f"[M5a] 通过：seed={seed}，引擎接受了「通召白兔」")
      return 0
    if result == "failed":
      print(f"  seed {seed}: 对局异常结束")
  print("[M5a] 失败：没有任何种子走到通召")
  return 1


if __name__ == "__main__":
  raise SystemExit(main())
