#!/usr/bin/env python3
"""ygopro-core 的 ctypes 绑定。

只包 `ocgapi.h` 里的 10 个函数和 4 个结构体。结构体字段顺序必须和 C 头文件完全一致，
否则不会报错，只会段错误——所以每个结构体都在注释里标了对应的 C 定义。

参考：
- `ocgapi.h` / `ocgapi_types.h`
- `ocg_constants.py`（由 `gen_constants.py` 生成）
"""

from __future__ import annotations

import ctypes
from ctypes import (
  POINTER,
  Structure,
  c_char_p,
  c_int,
  c_int32,
  c_uint8,
  c_uint16,
  c_uint32,
  c_uint64,
  c_void_p,
)
from pathlib import Path

# OCG_DuelCreationStatus
CREATION_SUCCESS = 0
CREATION_NO_OUTPUT = 1
CREATION_NOT_CREATED = 2
CREATION_NULL_DATA_READER = 3
CREATION_NULL_SCRIPT_READER = 4
CREATION_INCOMPATIBLE_LUA_API = 5
CREATION_NULL_RNG_SEED = 6

CREATION_NAMES = {
  CREATION_SUCCESS: "SUCCESS",
  CREATION_NO_OUTPUT: "NO_OUTPUT",
  CREATION_NOT_CREATED: "NOT_CREATED",
  CREATION_NULL_DATA_READER: "NULL_DATA_READER",
  CREATION_NULL_SCRIPT_READER: "NULL_SCRIPT_READER",
  CREATION_INCOMPATIBLE_LUA_API: "INCOMPATIBLE_LUA_API",
  CREATION_NULL_RNG_SEED: "NULL_RNG_SEED",
}

# OCG_DuelStatus
DUEL_END = 0
DUEL_AWAITING = 1
DUEL_CONTINUE = 2

DUEL_STATUS_NAMES = {DUEL_END: "END", DUEL_AWAITING: "AWAITING", DUEL_CONTINUE: "CONTINUE"}


class CardData(Structure):
  """OCG_CardData（ocgapi_types.h）。"""

  _fields_ = [
    ("code", c_uint32),
    ("alias", c_uint32),
    ("setcodes", POINTER(c_uint16)),
    ("type", c_uint32),
    ("level", c_uint32),
    ("attribute", c_uint32),
    ("race", c_uint64),
    ("attack", c_int32),
    ("defense", c_int32),
    ("lscale", c_uint32),
    ("rscale", c_uint32),
    ("link_marker", c_uint32),
  ]


class Player(Structure):
  """OCG_Player（ocgapi_types.h）。"""

  _fields_ = [
    ("startingLP", c_uint32),
    ("startingDrawCount", c_uint32),
    ("drawCountPerTurn", c_uint32),
  ]


class NewCardInfo(Structure):
  """OCG_NewCardInfo（ocgapi_types.h）。"""

  _fields_ = [
    ("team", c_uint8),
    ("duelist", c_uint8),
    ("code", c_uint32),
    ("con", c_uint8),
    ("loc", c_uint32),
    ("seq", c_uint32),
    ("pos", c_uint32),
  ]


# 回调类型：必须用 CFUNCTYPE，并且调用方要保持引用，否则 GC 后引擎回调会崩
DATA_READER = ctypes.CFUNCTYPE(None, c_void_p, c_uint32, POINTER(CardData))
DATA_READER_DONE = ctypes.CFUNCTYPE(None, c_void_p, POINTER(CardData))
SCRIPT_READER = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p, c_char_p)
LOG_HANDLER = ctypes.CFUNCTYPE(None, c_void_p, c_char_p, c_int)


class DuelOptions(Structure):
  """OCG_DuelOptions（ocgapi_types.h）。"""

  _fields_ = [
    ("seed", c_uint64 * 4),
    ("flags", c_uint64),
    ("team1", Player),
    ("team2", Player),
    ("cardReader", DATA_READER),
    ("payload1", c_void_p),
    ("scriptReader", SCRIPT_READER),
    ("payload2", c_void_p),
    ("logHandler", LOG_HANDLER),
    ("payload3", c_void_p),
    ("cardReaderDone", DATA_READER_DONE),
    ("payload4", c_void_p),
    ("enableUnsafeLibraries", c_uint8),
  ]


class Core:
  """一张已加载的 ocgcore 库。

  回调函数由这个对象持有（`self._keep`），一旦被 GC，引擎手里的函数指针就悬空了。
  """

  def __init__(self, dll_path: Path | str):
    self.dll_path = Path(dll_path)
    self.lib = ctypes.CDLL(str(self.dll_path))
    self._keep: list = []
    self._bind()

  def _bind(self) -> None:
    lib = self.lib
    lib.OCG_GetVersion.argtypes = [POINTER(c_int), POINTER(c_int)]
    lib.OCG_GetVersion.restype = None

    lib.OCG_CreateDuel.argtypes = [POINTER(c_void_p), POINTER(DuelOptions)]
    lib.OCG_CreateDuel.restype = c_int

    lib.OCG_DestroyDuel.argtypes = [c_void_p]
    lib.OCG_DestroyDuel.restype = None

    lib.OCG_DuelNewCard.argtypes = [c_void_p, POINTER(NewCardInfo)]
    lib.OCG_DuelNewCard.restype = None

    lib.OCG_StartDuel.argtypes = [c_void_p]
    lib.OCG_StartDuel.restype = None

    lib.OCG_DuelProcess.argtypes = [c_void_p]
    lib.OCG_DuelProcess.restype = c_int

    lib.OCG_DuelGetMessage.argtypes = [c_void_p, POINTER(c_uint32)]
    lib.OCG_DuelGetMessage.restype = c_void_p

    lib.OCG_DuelSetResponse.argtypes = [c_void_p, c_void_p, c_uint32]
    lib.OCG_DuelSetResponse.restype = None

    lib.OCG_LoadScript.argtypes = [c_void_p, c_char_p, c_uint32, c_char_p]
    lib.OCG_LoadScript.restype = c_int

    lib.OCG_DuelQueryField.argtypes = [c_void_p, POINTER(c_uint32)]
    lib.OCG_DuelQueryField.restype = c_void_p

    lib.OCG_DuelQueryLocation.argtypes = [c_void_p, POINTER(c_uint32), c_void_p]
    lib.OCG_DuelQueryLocation.restype = c_void_p

  def version(self) -> tuple[int, int]:
    major, minor = c_int(0), c_int(0)
    self.lib.OCG_GetVersion(ctypes.byref(major), ctypes.byref(minor))
    return major.value, minor.value

  def make_options(
    self,
    card_reader,
    script_reader,
    log_handler,
    *,
    seed: tuple[int, int, int, int] = (1, 2, 3, 4),
    flags: int = 0,
  ) -> DuelOptions:
    """把 Python 回调包成引擎要的函数指针，并保持引用。"""
    options = DuelOptions()
    options.seed = (c_uint64 * 4)(*seed)
    options.flags = c_uint64(flags)
    options.team1 = Player(startingLP=8000, startingDrawCount=5, drawCountPerTurn=1)
    options.team2 = Player(startingLP=8000, startingDrawCount=5, drawCountPerTurn=1)

    readers = (
      DATA_READER(card_reader),
      SCRIPT_READER(script_reader),
      LOG_HANDLER(log_handler),
      DATA_READER_DONE(lambda payload, data: None),
    )
    self._keep.extend(readers)
    options.cardReader, options.scriptReader, options.logHandler, options.cardReaderDone = readers
    return options

  def create_duel(self, options: DuelOptions) -> tuple[int, c_void_p | None]:
    duel = c_void_p()
    status = self.lib.OCG_CreateDuel(ctypes.byref(duel), ctypes.byref(options))
    return status, (duel if status == CREATION_SUCCESS else None)

  def destroy_duel(self, duel: c_void_p) -> None:
    self.lib.OCG_DestroyDuel(duel)
