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
