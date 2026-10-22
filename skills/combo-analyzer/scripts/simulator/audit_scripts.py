"""列出卡脚本 / 全局脚本用到、但脚本环境里没有定义的函数或常量。

脚本环境 = 引擎注册的 lua 函数（lib*.cpp 里的 LUA_FUNCTION 家族）
        + constant.lua / utility.lua / procedure.lua 里的定义
        + 卡脚本自己定义的局部函数。

对不上号的每一项都意味着某张卡一判定就抛 lua 错误——现象通常不是崩溃，
而是「效果/召唤静静地消失」。所以这个清单比任何日志都更早发现问题。

用法::

    python audit_scripts.py --core ../../vendor/ygopro-core-src --scripts .cache/ygopro-scripts
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

# 引擎注册函数：LUA_FUNCTION / LUA_STATIC_FUNCTION / LUA_FUNCTION_ALIAS / LUA_FUNCTION_EXISTING
CORE_PATTERNS = (
  re.compile(r"LUA_FUNCTION\(\s*(\w+)\s*\)"),
  re.compile(r"LUA_STATIC_FUNCTION\(\s*(\w+)\s*\)"),
  re.compile(r"LUA_FUNCTION_ALIAS\(\s*(\w+)\s*\)"),
  re.compile(r"LUA_FUNCTION_EXISTING\(\s*(\w+)\s*"),
)

# lua 侧定义：function X.Y(...) / X.Y = ... / function X(...)（全局函数）
LUA_METHOD = re.compile(r"\bfunction\s+(?:Card|Group|Effect|Duel|aux|Auxiliary|Debug)\.(\w+)\s*\(")
LUA_METHOD_ASSIGN = re.compile(
  r"^\s*(?:Card|Group|Effect|Duel|aux|Auxiliary|Debug)\.(\w+)\s*=", re.MULTILINE
)
LUA_FUNCTION = re.compile(r"^\s*function\s+(\w+)\s*\(", re.MULTILINE)
# 常量定义：NAME=... 或 NAME = ...（constant.lua 风格）
LUA_CONSTANT = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\s*=", re.MULTILINE)

# 使用处：obj:Method( 与 Card.Method / Duel.Method ...
USED_METHOD = re.compile(r":(\w+)\s*\(")
USED_STATIC = re.compile(r"\b(?:Card|Duel|Group|Effect|Debug)\.(\w+)")
USED_CONSTANT = re.compile(
  r"\b((?:EFFECT|LOCATION|TYPE|RACE|ATTRIBUTE|CATEGORY|SUMMON|REASON|POS|PHASE|CHAININFO|"
  r"STATUS|RESET|COUNTER|TIMING|HINT|LINK_MARKER|PLAYER|MATERIAL|EVENT)_[A-Z0-9_]+)\b"
)

GLOBALS = ("constant.lua", "utility.lua", "procedure.lua")

BUILTINS = {
  "format",
  "gsub",
  "match",
  "sub",
  "find",
  "gmatch",
  "rep",
  "len",
  "byte",
  "char",
  "upper",
  "lower",
  "reverse",
  "tostring",
  "tonumber",
  "type",
  "ipairs",
  "pairs",
  "next",
  "select",
  "unpack",
  "insert",
  "remove",
  "concat",
  "sort",
  "floor",
  "ceil",
  "max",
  "min",
  "abs",
  "random",
  "randomseed",
  "sqrt",
  "setmetatable",
  "getmetatable",
  "rawget",
  "rawset",
  "pcall",
  "error",
  "assert",
  "print",
  "dofile",
  "load",
  "split",
  "trim",
  "extract",
  "band",
  "bor",
  "bxor",
  "bnot",
  "lshift",
  "rshift",
  "test",
  "replace",
  "isIn",
  "getn",
  "add",
  "clone",
  "shuffle",
  "filter",
  "keys",
  "count",
  "func",
  "tag",
  "push",
  "new",
  "index",
  "delete",
  "get",
  "set",
  "merge",
  "copy",
  "clear",
  "stat",
  "lines",
  "open",
  "close",
  "write",
  "read",
}


def core_defined(core: Path) -> set[str]:
  names: set[str] = set()
  for path in core.rglob("*"):
    if path.suffix not in {".cpp", ".h"}:
      continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for pattern in CORE_PATTERNS:
      names.update(pattern.findall(text))
  return names


def lua_defined(scripts: Path) -> tuple[set[str], set[str]]:
  functions: set[str] = set()
  constants: set[str] = set()
  for path in sorted(scripts.glob("*.lua")):
    text = path.read_text(encoding="utf-8", errors="ignore")
    functions.update(LUA_METHOD.findall(text))
    functions.update(LUA_METHOD_ASSIGN.findall(text))
    functions.update(LUA_FUNCTION.findall(text))
    constants.update(LUA_CONSTANT.findall(text))
  return functions, constants


def collect(scripts: Path, pattern: re.Pattern) -> dict[str, list[str]]:
  found: dict[str, list[str]] = {}
  for path in sorted(scripts.glob("*.lua")):
    text = path.read_text(encoding="utf-8", errors="ignore")
    for name in set(pattern.findall(text)):
      found.setdefault(name, []).append(path.name)
  return found


def report(title: str, missing: dict[str, list[str]], note) -> int:
  if not missing:
    print(f"{title}：没有缺失。")
    return 0
  print(f"{title}：缺 {len(missing)} 项")
  for name in sorted(missing, key=lambda n: -len(missing[n])):
    files = missing[name]
    sample = ", ".join(files[:3]) + (" ..." if len(files) > 3 else "")
    glob = " [全局]" if any(f in GLOBALS for f in files) else ""
    print(f"  {name:<24} 用在 {len(files):>3} 个脚本{glob}：{sample}")
  return 1


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="审计脚本环境里缺失的函数与常量。")
  parser.add_argument("--core", type=Path, required=True)
  parser.add_argument("--scripts", type=Path, required=True)
  args = parser.parse_args(argv)

  engine = core_defined(args.core)
  lua_funcs, lua_consts = lua_defined(args.scripts)
  defined = engine | lua_funcs
  print(f"引擎注册 {len(engine)}，lua 定义 {len(lua_funcs)}，常量 {len(lua_consts)}\n")

  used_funcs = collect(args.scripts, USED_METHOD)
  for name, files in collect(args.scripts, USED_STATIC).items():
    used_funcs.setdefault(name, []).extend(files)
  missing_funcs = {
    name: files
    for name, files in used_funcs.items()
    if name not in defined and name not in BUILTINS
  }

  used_consts = collect(args.scripts, USED_CONSTANT)
  missing_consts = {name: files for name, files in used_consts.items() if name not in lua_consts}

  status = report("缺失函数", missing_funcs, None)
  print()
  status |= report("缺失常量", missing_consts, None)
  return status


if __name__ == "__main__":
  raise SystemExit(main())
