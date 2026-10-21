#!/usr/bin/env python3
"""逐关验证引擎能不能用：M1 建局 → M2 装牌 → M3 脚本 → M4 首条消息。

每一步都独立报告，走到哪一步失败就停在哪一步——因为后面每一步都依赖前面，
而失败症状往往都是「什么都没有发生」。

用法::

    python probe.py --dll build/ocgcore.dll
    python probe.py --dll build/ocgcore.dll --cdb cards.cdb --deck deck_raw.json --scripts .cache/ygopro-scripts
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sqlite3
from pathlib import Path

import messages as messages_module
import ocgcore
from ocg_constants import (
  LOCATION_DECK,
  LOCATION_EXTRA,
  MESSAGES,
  MSG_DRAW,
  MSG_NEW_PHASE,
  MSG_NEW_TURN,
)

DECK_LOC = LOCATION_DECK
EXTRA_LOC = LOCATION_EXTRA


def ocgcore_message_name(opcode: int) -> str:
  return MESSAGES.get(opcode, f"opcode={opcode}")


class CardTable:
  """cards.cdb 的 datas 表读取器，供 cardReader 回调使用。"""

  def __init__(self, cdb: Path):
    self.connection = sqlite3.connect(cdb)
    self.connection.row_factory = sqlite3.Row
    self.missing: list[int] = []

  def lookup(self, code: int) -> sqlite3.Row | None:
    row = self.connection.execute("SELECT * FROM datas WHERE id = ?", (code,)).fetchone()
    if row is None:
      self.missing.append(code)
    return row


def make_card_reader(table: CardTable, keep: list):
  """返回一个 cardReader 回调；setcodes 的内存挂在 keep 上，由 cardReaderDone 释放。"""

  def reader(payload, code, data):
    row = table.lookup(code)
    if row is None:
      return
    keys = row.keys()
    data.contents.code = code
    data.contents.alias = row["alias"] if "alias" in keys else 0
    data.contents.type = row["type"] or 0
    data.contents.level = row["level"] or 0
    data.contents.attribute = row["attribute"] or 0
    data.contents.race = row["race"] or 0
    data.contents.attack = row["atk"] or 0
    data.contents.defense = row["def"] or 0
    data.contents.lscale = row["lscale"] if "lscale" in keys else 0
    data.contents.rscale = row["rscale"] if "rscale" in keys else 0
    data.contents.link_marker = row["link_marker"] if "link_marker" in keys else 0
    data.contents.setcodes = None

  return reader


def read_ydk(path: Path) -> dict[str, list[int]]:
  """按 #main / #extra / !side 分段读卡号。"""
  sections: dict[str, list[int]] = {"main": [], "extra": [], "side": []}
  current = None
  for line in path.read_text(encoding="utf-8-sig").splitlines():
    text = line.strip()
    if text == "#main":
      current = "main"
    elif text == "#extra":
      current = "extra"
    elif text == "!side":
      current = "side"
    elif text and text.isdigit() and current:
      sections[current].append(int(text))
  return sections


def load_deck(path: Path, table: CardTable) -> dict[str, list[int]]:
  """支持 .ydk（直接读卡号）和 deck_raw.json（按卡名查号）。"""
  if path.suffix.lower() == ".ydk":
    return read_ydk(path)

  data = json.loads(path.read_text(encoding="utf-8-sig"))
  result: dict[str, list[int]] = {"main": [], "extra": []}
  for section in ("main", "extra"):
    for card in data[section]:
      row = table.connection.execute(
        "SELECT id FROM texts WHERE name = ?", (card["name"],)
      ).fetchone()
      if row:
        result[section].extend([row[0]] * card["count"])
  return result


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="逐关探测 ocgcore 是否可用。")
  parser.add_argument("--dll", type=Path, required=True, help="ocgcore.dll")
  parser.add_argument("--cdb", type=Path, help="cards.cdb（M2 需要）")
  parser.add_argument("--ydk", type=Path, help=".ydk（M2 需要，直接读卡号）")
  parser.add_argument("--deck", type=Path, help="deck_raw.json（M2 需要，按卡名查号）")
  parser.add_argument("--scripts", type=Path, help="卡脚本目录（M3 需要）")
  parser.add_argument("-v", "--verbose", action="store_true", help="打印脚本加载的完整清单")
  args = parser.parse_args(argv)

  core = ocgcore.Core(args.dll)
  major, minor = core.version()
  print(f"[M0] ocgcore {major}.{minor} 已加载")

  keep: list = []
  table = CardTable(args.cdb) if args.cdb else None
  logs: list[str] = []

  loaded_scripts: list[str] = []
  missing_scripts: list[str] = []

  def script_reader(payload, duel, name):
    """引擎要脚本时，读文件并交给 OCG_LoadScript——返回 1 只表示「找到了」，不够。"""
    if not args.scripts:
      return 0
    filename = name.decode("utf-8", "replace")
    path = args.scripts / filename
    if not path.is_file():
      missing_scripts.append(filename)
      return 0
    data = path.read_bytes()
    result = core.lib.OCG_LoadScript(duel, data, len(data), filename.encode())
    if result <= 0:
      missing_scripts.append(filename)
    else:
      loaded_scripts.append(filename)
    return result

  def log_handler(payload, text, kind):
    message = text.decode("utf-8", "replace")
    logs.append(message)

  card_reader = make_card_reader(table, keep) if table else (lambda *a: None)
  options = core.make_options(card_reader, script_reader, log_handler)
  status, duel = core.create_duel(options)
  print(f"[M1] CreateDuel -> {ocgcore.CREATION_NAMES.get(status, status)}")
  if duel is None:
    return 1

  # 全局脚本要自己加载：引擎不会通过 scriptReader 索要它们，
  # 而卡脚本第一行 `local s,id=GetID()` 依赖 utility.lua，
  # 连接怪兽的 `aux.AddLinkProcedure` 依赖 procedure.lua。顺序不能颠倒。
  if args.scripts:
    for name in ("constant.lua", "utility.lua", "procedure.lua"):
      path = args.scripts / name
      if not path.is_file():
        print(f"[M3] 缺少全局脚本 {name}（{args.scripts}）")
        core.destroy_duel(duel)
        return 1
      data = path.read_bytes()
      result = core.lib.OCG_LoadScript(duel, data, len(data), name.encode())
      print(f"[M3] 加载全局脚本 {name} -> {result}")
      if result <= 0:
        core.destroy_duel(duel)
        return 1

  deck_path = args.ydk or args.deck
  if not (args.cdb and deck_path):
    core.destroy_duel(duel)
    print("[M2] 跳过（没给 --cdb / --ydk 或 --deck）")
    return 0

  deck = load_deck(deck_path, table)
  added = 0
  for section, loc in (("main", DECK_LOC), ("extra", EXTRA_LOC)):
    for seq, code in enumerate(deck[section]):
      info = ocgcore.NewCardInfo(team=0, duelist=0, code=code, con=0, loc=loc, seq=seq, pos=0)
      core.lib.OCG_DuelNewCard(duel, ctypes.byref(info))
      added += 1
  print(
    f"[M2] 装入 {added} 张卡"
    f"（主 {len(deck['main'])} / 额外 {len(deck['extra'])}）"
    + (f"，{len(table.missing)} 张查不到" if table.missing else "")
  )

  if not args.scripts:
    core.destroy_duel(duel)
    print("[M3] 跳过（没给 --scripts）")
    return 0

  core.lib.OCG_StartDuel(duel)
  status = core.lib.OCG_DuelProcess(duel)
  length = ctypes.c_uint32(0)
  pointer = core.lib.OCG_DuelGetMessage(duel, ctypes.byref(length))
  buffer = ctypes.string_at(pointer, length.value) if pointer else b""
  parsed = messages_module.split(buffer)
  print(
    f"[M4] StartDuel -> {ocgcore.DUEL_STATUS_NAMES.get(status, status)}，"
    f"{length.value} 字节 / {len(parsed)} 条消息；"
    f"卡脚本 加载 {len(loaded_scripts)} / 未加载 {len(missing_scripts)}"
  )
  if args.verbose:
    print(f"     已加载: {', '.join(loaded_scripts)}")
    print(f"     缺失:   {', '.join(missing_scripts)}")
  if missing_scripts:
    print(f"     缺失示例: {', '.join(missing_scripts[:5])}")

  for message in parsed[:6]:
    detail = ""
    if message.type == MSG_DRAW:
      info = messages_module.decode_draw(message)
      detail = f" player={info['player']} 抽 {len(info['cards'])} 张"
    elif message.type == MSG_NEW_TURN:
      detail = f" player={messages_module.decode_new_turn(message)['player']}"
    elif message.type == MSG_NEW_PHASE:
      detail = f" phase={messages_module.decode_new_phase(message)['phase']}"
    print(f"     {message.name}{detail}")
  if args.verbose:
    print(f"     已加载: {', '.join(loaded_scripts)}")
    print(f"     缺失:   {', '.join(missing_scripts)}")
  if logs:
    print(f"     引擎日志 {len(logs)} 条，首条: {logs[0][:80]}")

  core.destroy_duel(duel)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
