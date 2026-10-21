#!/usr/bin/env python3
"""把 ygopro-core 的 `ocgapi_constants.h` 转成 Python 常量模块。

接引擎时需要大量「数字 ↔ 名字」的对应：`cards.cdb` 的 type 位掩码、
`OCG_DuelQueryLocation` 的 QUERY_* 标志、消息 opcode、区域掩码……

这些值全部来自引擎头文件，不需要引擎本身。先转好一份，接引擎那天直接用，
也方便任何时候对照「引擎返回的 0x4000000 是什么」。

用法::

    python gen_constants.py                     # 下载并生成 ocg_constants.py
    python gen_constants.py --file header.h     # 用本地文件
    python gen_constants.py --check             # 只校验现有模块是否过期
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://raw.githubusercontent.com/edo9300/ygopro-core/master/ocgapi_constants.h"

DEFINE_RE = re.compile(r"^#define\s+([A-Z][A-Z0-9_]*)\s+(.+?)\s*(?:/\*.*)?$")
ENUM_RE = re.compile(r"enum\s+(?:class\s+)?(\w+)\s*(?::\s*\w+)?\s*\{(.*?)\}", re.DOTALL)

# 只允许这些字符，避免把上游文件里的任意表达式当代码执行
SAFE_EXPR = re.compile(r"^[0-9A-Za-z_\s|&()<>+~*/-]+$")

GROUPS = (
  ("LOCATIONS", "LOCATION_"),
  ("POSITIONS", "POS_"),
  ("TYPES", "TYPE_"),
  ("ATTRIBUTES", "ATTRIBUTE_"),
  ("RACES", "RACE_"),
  ("STATUSES", "STATUS_"),
  ("QUERIES", "QUERY_"),
  ("LINK_MARKERS", "LINK_MARKER_"),
  ("MESSAGES", "MSG_"),
  ("PHASES", "PHASE_"),
  ("REASONS", "REASON_"),
  ("OPTIONS", "DUEL_"),
)


def fetch(url: str, cache: Path) -> str:
  if cache.is_file():
    return cache.read_text(encoding="utf-8")
  with urllib.request.urlopen(url, timeout=30) as response:
    text = response.read().decode("utf-8")
  cache.parent.mkdir(parents=True, exist_ok=True)
  cache.write_text(text, encoding="utf-8")
  return text


def try_eval(expr: str, env: dict[str, int]) -> int | None:
  """解析 `(A | B)` 这类定义；解析不了就返回 None，交给下一轮。"""
  if not SAFE_EXPR.match(expr):
    return None
  try:
    return int(eval(expr, {"__builtins__": {}}, dict(env)))
  except (ValueError, SyntaxError, NameError, TypeError):
    return None


def parse(text: str) -> dict[str, int]:
  values: dict[str, int] = {}
  pending: list[tuple[str, str]] = []

  for line in text.splitlines():
    if line.startswith("#define"):
      match = DEFINE_RE.match(line)
      if match and not match.group(1).endswith("_H"):
        pending.append((match.group(1), match.group(2)))

  # 多轮解析，让 LOCATION_ONFIELD 这类引用前面常量的定义也能算出来
  for _ in range(5):
    progressed = False
    for name, expr in list(pending):
      if name in values:
        pending.remove((name, expr))
        continue
      value = try_eval(expr, values)
      if value is None:
        continue
      values[name] = value
      pending.remove((name, expr))
      progressed = True
    if not progressed:
      break

  return values


def render(values: dict[str, int], source: str) -> str:
  lines = [
    '"""ygopro-core 常量表（自动生成，勿手改）。',
    "",
    f"来源：{source}",
    "",
    "生成方式：`python gen_constants.py`（见同目录 README）。",
    '"""',
    "",
    "from __future__ import annotations",
    "",
  ]

  for group, prefix in GROUPS:
    names = sorted((name for name in values if name.startswith(prefix)), key=lambda n: values[n])
    if not names:
      continue
    lines.append(f"# --- {group} ---")
    for name in names:
      lines.append(f"{name} = {values[name]:#x}")
    lines.append(f"{group} = {{")
    seen: set[int] = set()
    for name in names:
      # 同组里偶尔有两个名字共用同一个值（别名 / 模式组合），反向表只留第一个
      if values[name] in seen:
        continue
      seen.add(values[name])
      lines.append(f"    {values[name]:#x}: {name!r},")
    lines.append("}")
    lines.append("")

  lines += [
    "",
    "",
    "def describe(value: int, table: dict[int, str]) -> str:",
    '  """把位掩码翻成人能读的名字，例如 0x0c → \'LOCATION_MZONE|LOCATION_SZONE\'。',
    "",
    "  只按「单个位」拆分，避免 LOCATION_ONFIELD 这类组合常量把父项也带出来；",
    "  如果整个值恰好有同名常量，在末尾用括号补上。",
    '  """',
    "  parts = [",
    "    name",
    "    for bit, name in sorted(table.items())",
    "    if bit and bit & (bit - 1) == 0 and value & bit == bit",
    "  ]",
    '  text = "|".join(parts) if parts else hex(value)',
    "  exact = table.get(value)",
    "  if exact and exact not in parts:",
    '    text += f" ({exact})"',
    "  return text",
    "",
  ]
  return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="从 ocgapi_constants.h 生成 Python 常量模块。")
  parser.add_argument("--url", default=DEFAULT_URL, help="头文件地址")
  parser.add_argument("--file", type=Path, help="本地头文件（优先于 --url）")
  parser.add_argument("--cache", type=Path, default=Path(".cache/ocgapi_constants.h"))
  parser.add_argument("-o", "--out", type=Path, default=Path("ocg_constants.py"))
  parser.add_argument("--check", action="store_true", help="只报告数量，不写文件")
  args = parser.parse_args(argv)

  text = args.file.read_text(encoding="utf-8") if args.file else fetch(args.url, args.cache)
  values = parse(text)
  if not values:
    print("错误：没有解析出任何常量", file=sys.stderr)
    return 1

  body = render(values, str(args.file or args.url))
  if args.check:
    print(f"解析出 {len(values)} 个常量（未写文件）")
    return 0

  args.out.write_text(body, encoding="utf-8")
  groups = sum(1 for group, prefix in GROUPS if any(n.startswith(prefix) for n in values))
  print(f"已写入 {args.out}：{len(values)} 个常量，{groups} 个分组")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
