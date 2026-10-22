#!/usr/bin/env python3
"""解析 .yrp3d（YGOPro Unity / MDPro3 录像），还原每一手出牌顺序。

格式（参考 npm 包 ygopro-yrp3d-encode）：

    包序列： uint8 type + uint32 length + payload
    type 235 = 名字包（6 个 100 字节的 UTF-16 名字 + masterRule）
    type 231 = 录像数据，其余 MSG_*（4=START, 90=DRAW, 50=MOVE, 70=CHAINING ...）
    引擎消息的 payload 就是 ``OCG_DuelGetMessage`` 里的内容，但少了外层的长度前缀。

用法::

    python replay_parse.py <目录或文件> [--cdb cards.cdb] [--turn 1]
"""

from __future__ import annotations

import argparse
import sqlite3
import struct
from dataclasses import dataclass, field
from pathlib import Path

from ocg_constants import (
  MSG_CHAINING,
  MSG_MOVE,
  MSG_NEW_PHASE,
  MSG_NEW_TURN,
  MSG_SET,
  MSG_SPSUMMONING,
  MSG_SUMMONING,
)

PACKET_NAME = 235
PACKET_REPLAY = 231


@dataclass
class Event:
  turn: int
  kind: str
  code: int = 0
  detail: str = ""


@dataclass
class Replay:
  path: Path
  names: list[str] = field(default_factory=list)
  events: list[Event] = field(default_factory=list)


LOCATION_NAMES = {
  1: "DECK",
  2: "HAND",
  4: "MZONE",
  8: "SZONE",
  16: "GRAVE",
  32: "REMOVED",
  64: "EXTRA",
  128: "OVERLAY",
}


def loc_name(value: int) -> str:
  return LOCATION_NAMES.get(value, hex(value))


def read_packets(data: bytes) -> list[tuple[int, bytes]]:
  packets = []
  pos = 0
  while pos + 5 <= len(data):
    kind = data[pos]
    length = struct.unpack_from("<I", data, pos + 1)[0]
    payload = data[pos + 5 : pos + 5 + length]
    if len(payload) != length:
      break
    packets.append((kind, payload))
    pos += 5 + length
  return packets


def read_name_field(payload: bytes, index: int) -> str:
  start = index * 100
  raw = payload[start : start + 100]
  text = raw.decode("utf-16-le", "ignore").split("\x00")[0]
  return text.strip()


def card_of(payload: bytes) -> int:
  """这几个消息的 payload 都以 uint32 卡号开头（后续 loc_info 是紧凑的 u8 变体）。"""
  if len(payload) < 4:
    return 0
  return struct.unpack_from("<I", payload, 0)[0]


def parse(path: Path) -> Replay:
  replay = Replay(path=path)
  data = path.read_bytes()
  packets = read_packets(data)

  turn = 0
  phase = 0
  for kind, payload in packets:
    if kind == PACKET_NAME and not replay.names:
      replay.names = [read_name_field(payload, i) for i in (0, 3)]
      continue
    if kind < 4 or kind > 200:
      continue
    if kind == MSG_NEW_TURN:
      turn += 1
      replay.events.append(Event(turn, "turn"))
    elif kind == MSG_NEW_PHASE:
      phase = struct.unpack_from("<H", payload, 0)[0]
      replay.events.append(Event(turn, "phase", detail=hex(phase)))
    elif kind in (MSG_SUMMONING, MSG_SPSUMMONING):
      label = "advent" if kind == MSG_SPSUMMONING else "summon"
      replay.events.append(Event(turn, label, card_of(payload)))
    elif kind == MSG_SET:
      replay.events.append(Event(turn, "set", card_of(payload)))
    elif kind == MSG_CHAINING:
      replay.events.append(Event(turn, "effect", card_of(payload)))
    elif kind == MSG_MOVE and len(payload) >= 12:
      # 紧凑版：code(4) + 起点(ctrl,loc,seq,pos 各 1 字节) + 终点 + reason
      code = struct.unpack_from("<I", payload, 0)[0]
      from_loc = payload[5]
      to_loc = payload[9]
      replay.events.append(
        Event(turn, "move", code, detail=f"{loc_name(from_loc)}->{loc_name(to_loc)}")
      )
  return replay


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="解析 .yrp3d 录像，打印出牌顺序。")
  parser.add_argument("target", type=Path, help="录像文件或目录")
  parser.add_argument("--cdb", type=Path, required=True)
  parser.add_argument("--turn", type=int, default=1, help="只看第几个回合（0 = 全部）")
  args = parser.parse_args(argv)

  connection = sqlite3.connect(args.cdb)
  names = {row[0]: row[1] for row in connection.execute("SELECT id, name FROM texts")}

  files = (
    [args.target]
    if args.target.is_file()
    else sorted(args.target.glob("*.yrp3d"), key=lambda p: p.stat().st_mtime)
  )
  for path in files:
    replay = parse(path)
    print(f"\n=== {path.name} ===")
    print(f"玩家: {replay.names}")
    for event in replay.events:
      if args.turn and event.turn != args.turn:
        continue
      if event.kind == "turn":
        print(f"  --- 回合 {event.turn} ---")
      elif event.kind == "phase":
        continue
      else:
        name = names.get(event.code, f"#{event.code}")
        print(f"    {event.kind:7s} {name}  {event.detail}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
