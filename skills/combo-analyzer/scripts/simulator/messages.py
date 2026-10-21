#!/usr/bin/env python3
"""ocgcore 消息流解析。

帧格式（见 `duel.cpp` 的 `generate_buffer`）：

    uint32 size      整条消息的字节数（含 1 字节的类型）
    uint8  type      消息类型，见 ocg_constants.MESSAGES
    ...              payload

类型是**单字节**，不是 uint32——这一点最容易错：把类型读成 4 字节会把 payload 的前 3 字节
吞进去，后面全部错位，而且引擎不会报错。

目前只解「验证做场线」用得上的几条；其余按 size 跳过并保留原始字节，
需要时再补解码。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ocg_constants import MESSAGES


@dataclass
class Message:
  type: int
  payload: bytes

  @property
  def name(self) -> str:
    return MESSAGES.get(self.type, f"opcode={self.type}")

  def __repr__(self) -> str:
    return f"<{self.name} {len(self.payload)}B>"


def split(buffer: bytes) -> list[Message]:
  """把一次 GetMessage 的缓冲区切成消息列表。"""
  messages: list[Message] = []
  offset = 0
  while offset + 5 <= len(buffer):
    size = struct.unpack_from("<I", buffer, offset)[0]
    if size < 1 or offset + 4 + size > len(buffer):
      break
    message_type = buffer[offset + 4]
    payload = buffer[offset + 5 : offset + 4 + size]
    messages.append(Message(message_type, payload))
    offset += 4 + size
  return messages


def decode_draw(message: Message) -> dict:
  """MSG_DRAW: uint8 player, uint32 count, count × (uint32 code, uint32 position)。"""
  player = message.payload[0]
  count = struct.unpack_from("<I", message.payload, 1)[0]
  cards = []
  offset = 5
  for _ in range(count):
    code, position = struct.unpack_from("<II", message.payload, offset)
    cards.append({"code": code, "position": position})
    offset += 8
  return {"player": player, "cards": cards}


def decode_new_phase(message: Message) -> dict:
  """MSG_NEW_PHASE: uint16 phase。"""
  return {"phase": struct.unpack_from("<H", message.payload, 0)[0]}


def decode_new_turn(message: Message) -> dict:
  """MSG_NEW_TURN: uint32 player（旧版本没有该字段时返回 None）。"""
  if len(message.payload) < 4:
    return {"player": None}
  return {"player": struct.unpack_from("<I", message.payload, 0)[0]}


def decode_idlecmd(message: Message) -> dict:
  """MSG_SELECT_IDLECMD（playerop.cpp 的 SelectIdleCmd::step 0）。

  布局：

      uint8  player
      uint32 n_summon;     n × (uint32 code, uint8 ctrl, uint8 loc, uint32 seq)
      uint32 n_spsummon;   n × (同上)
      uint32 n_reposition; n × (uint32 code, uint8 ctrl, uint8 loc, uint8  seq)   <- seq 是 uint8
      uint32 n_mset;       n × (同上，seq 是 uint32)
      uint32 n_sset;       n × (同上)
      uint32 n_activate;   n × (uint32 code, uint8 ctrl, uint8 loc, uint32 seq,
                                uint64 description, uint8 client_mode)
      uint8  to_bp
      uint8  to_ep
      uint8  can_shuffle

  注意 `repositionable` 那一组的 sequence 是 **uint8**，和其余组不一样。
  """
  payload = message.payload
  offset = 1
  player = payload[0]

  def read_entries(sequence_size: int) -> list[dict]:
    nonlocal offset
    count = struct.unpack_from("<I", payload, offset)[0]
    offset += 4
    entries = []
    for _ in range(count):
      code, controller, location = struct.unpack_from("<IBB", payload, offset)
      offset += 6
      if sequence_size == 4:
        sequence = struct.unpack_from("<I", payload, offset)[0]
        offset += 4
      else:
        sequence = payload[offset]
        offset += 1
      entries.append(
        {"code": code, "controller": controller, "location": location, "sequence": sequence}
      )
    return entries

  result = {
    "player": player,
    "summon": read_entries(4),
    "spsummon": read_entries(4),
    "reposition": read_entries(1),
    "mset": read_entries(4),
    "sset": read_entries(4),
    "activate": [],
  }

  count = struct.unpack_from("<I", payload, offset)[0]
  offset += 4
  for _ in range(count):
    code, controller, location = struct.unpack_from("<IBB", payload, offset)
    offset += 6
    sequence = struct.unpack_from("<I", payload, offset)[0]
    offset += 4
    description = struct.unpack_from("<Q", payload, offset)[0]
    offset += 8
    client_mode = payload[offset]
    offset += 1
    result["activate"].append(
      {
        "code": code,
        "controller": controller,
        "location": location,
        "sequence": sequence,
        "description": description,
        "client_mode": client_mode,
      }
    )

  result["to_bp"] = payload[offset]
  result["to_ep"] = payload[offset + 1]
  result["can_shuffle"] = payload[offset + 2]
  return result


# 响应里的动作编号（playerop.cpp：t = v & 0xffff, s = v >> 16）
IDLE_SUMMON = 0
IDLE_SPSUMMON = 1
IDLE_REPOSITION = 2
IDLE_MSET = 3
IDLE_SSET = 4
IDLE_ACTIVATE = 5
IDLE_TO_BP = 6
IDLE_TO_EP = 7
IDLE_SHUFFLE = 8


def encode_idlecmd_response(action: int, index: int = 0) -> bytes:
  """SELECT_IDLECMD 的回应：低 16 位是动作类型，高 16 位是选项下标。"""
  return struct.pack("<I", ((index & 0xFFFF) << 16) | (action & 0xFFFF))


def decode_place(message: Message) -> dict:
  """MSG_SELECT_PLACE / MSG_SELECT_DISFIELD：uint8 player, uint8 count, uint32 flag。

  `flag` 是可选区域的位掩码：bit 0~6 = 主怪兽区 1~7，bit 8~12 = 魔陷区 1~5。
  """
  player, count = struct.unpack_from("<BB", message.payload, 0)
  flag = struct.unpack_from("<I", message.payload, 2)[0]
  return {"player": player, "count": count, "flag": flag}


def zones_from_flag(flag: int) -> list[int]:
  """把区域掩码翻成可用格子列表（先怪兽区，再魔陷区）。

  **置位表示「不可用」**：引擎传的是禁用掩码，例如 0xffffffe0 表示 0~4 号怪兽区可用。
  这一点和直觉相反，按「置位=可用」解析会一直收到 MSG_RETRY。
  """
  zones = [index for index in range(7) if not flag & (1 << index)]
  zones += [8 + index for index in range(5) if not flag & (1 << (8 + index))]
  return zones


def encode_place_response(player: int, location: int, sequence: int) -> bytes:
  """SELECT_PLACE 的回应：每个选择 3 字节 (player, location, sequence)。"""
  return bytes([player & 0xFF, location & 0xFF, sequence & 0xFF])
