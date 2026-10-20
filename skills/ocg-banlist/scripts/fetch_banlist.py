#!/usr/bin/env python3
"""获取 YGOCore 的 OCG / TCG 禁限卡表，并可校验一副 .ydk 是否超限。

数据源是 YGOCore 客户端使用的 ``lflist.conf``：一个文件里并列了历年的 OCG 与 TCG
列表，每行是 ``<passcode> <限制数> --<卡名>``。``cards.cdb`` 本身不含禁限信息
（mycard/ygopro-database 甚至把 lflist.conf 写进了 .gitignore），所以必须单独获取。

用法::

    python fetch_banlist.py                        # 最新 OCG 列表的摘要
    python fetch_banlist.py --tcg                  # 最新 TCG 列表
    python fetch_banlist.py --list 2026.7          # 指定列表
    python fetch_banlist.py --format json -o ocg.json
    python fetch_banlist.py --check deck.ydk       # 校验一副牌
    python fetch_banlist.py --file ./lflist.conf   # 用本地文件（离线）
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

DEFAULT_URLS = (
  "https://raw.githubusercontent.com/Fluorohydride/ygopro/master/lflist.conf",
  "https://raw.githubusercontent.com/mycard/ygopro/master/lflist.conf",
)

FORBIDDEN = 0
LIMITED = 1
SEMI_LIMITED = 2
UNLIMITED = 3


def load_text(urls: tuple[str, ...], path: Path | None) -> tuple[str, str]:
  """读取 lflist.conf，返回 (内容, 来源说明)。给了本地文件就不联网。"""
  if path is not None:
    return path.read_text(encoding="utf-8"), str(path)

  last_error: Exception | None = None
  for url in urls:
    try:
      with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8"), url
    except Exception as exc:  # 网络问题逐个源重试
      last_error = exc
  raise SystemExit(f"无法下载 lflist.conf：{last_error}")


def parse_lists(text: str) -> list[tuple[str, dict[int, tuple[int, str]]]]:
  """把整个文件切成 [(列表名, {passcode: (限制数, 卡名)})]。"""
  lists: list[tuple[str, dict[int, tuple[int, str]]]] = []
  current: dict[int, tuple[int, str]] | None = None

  for raw in text.splitlines():
    line = raw.strip()
    if not line:
      continue
    if line.startswith("!"):
      current = {}
      lists.append((line[1:].strip(), current))
      continue
    if line.startswith("#") or current is None:
      continue

    parts = line.split(maxsplit=2)
    if len(parts) < 2:
      continue
    try:
      passcode, limit = int(parts[0]), int(parts[1])
    except ValueError:
      continue
    name = parts[2].lstrip("-").strip() if len(parts) > 2 else ""
    current[passcode] = (limit, name)

  return lists


def pick_list(
  lists: list[tuple[str, dict[int, tuple[int, str]]]], name: str | None, tcg: bool
) -> tuple[str, dict[int, tuple[int, str]]]:
  """按名字精确选，或者按 OCG/TCG 选文件里最新的那一份。"""
  if name is not None:
    for list_name, cards in lists:
      if list_name.lower() == name.lower():
        return list_name, cards
    available = ", ".join(list_name for list_name, _ in lists[:6])
    raise SystemExit(f"没有列表 {name!r}；可用的有：{available} ...")

  for list_name, cards in lists:
    if ("tcg" in list_name.lower()) == tcg:
      return list_name, cards
  raise SystemExit("lflist.conf 里没有找到可用的列表")


def read_ydk(path: Path) -> Counter:
  """统计 .ydk 里每个 passcode 的张数；#main/#extra/!side 之外的段忽略。"""
  counts: Counter = Counter()
  section: str | None = None

  for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line:
      continue
    lowered = line.lower()
    if lowered.startswith("#main"):
      section = "main"
      continue
    if lowered.startswith("#extra"):
      section = "extra"
      continue
    if lowered.startswith("!side"):
      section = "side"
      continue
    if line.startswith("#"):
      continue
    if section is not None and line.isdigit():
      counts[int(line)] += 1

  return counts


def check_deck(
  deck_path: Path, list_name: str, cards: dict[int, tuple[int, str]]
) -> int:
  """校验一副牌相对该列表是否超限，返回退出码。"""
  counts = read_ydk(deck_path)
  total = sum(counts.values())
  print(f"{deck_path}：{total} 张，对照列表 {list_name}")

  violations: list[tuple[int, int, int, str]] = []
  for passcode, count in sorted(counts.items()):
    limit, name = cards.get(passcode, (UNLIMITED, ""))
    if count > limit:
      violations.append((passcode, count, limit, name))

  if not violations:
    print("通过：没有卡片超过限制。")
    return 0

  print(f"违规 {len(violations)} 处：")
  for passcode, count, limit, name in violations:
    label = "禁止" if limit == FORBIDDEN else f"限制 {limit}"
    print(f"  [超限] {passcode:<9} 带 {count} 张，{label}  {name}")
  return 1


def describe(cards: dict[int, tuple[int, str]]) -> str:
  buckets = Counter(limit for limit, _ in cards.values())
  return (
    f"受限制卡 {len(cards)} 张"
    f"（禁止 {buckets[FORBIDDEN]} / 限制 {buckets[LIMITED]} / 准限制 {buckets[SEMI_LIMITED]}）"
  )


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(
    description="获取 YGOCore 的 OCG/TCG 禁限卡表，并可校验 .ydk 是否超限。",
  )
  parser.add_argument("--list", dest="list_name", help="列表名，例如 2026.10")
  parser.add_argument("--tcg", action="store_true", help="选择 TCG 列表（默认 OCG）")
  parser.add_argument("--file", type=Path, help="本地 lflist.conf（离线使用）")
  parser.add_argument("--url", action="append", help="下载地址，可重复")
  parser.add_argument("--format", choices=["text", "json", "csv"], default="text")
  parser.add_argument("-o", "--output", type=Path, help="输出文件，默认打印到标准输出")
  parser.add_argument("--check", type=Path, metavar="YDK", help="校验这副 .ydk")
  args = parser.parse_args(argv)

  text, source = load_text(tuple(args.url) if args.url else DEFAULT_URLS, args.file)
  lists = parse_lists(text)
  if not lists:
    raise SystemExit("lflist.conf 里没有解析到任何列表")

  list_name, cards = pick_list(lists, args.list_name, args.tcg)
  is_tcg = "tcg" in list_name.lower()

  if args.check is not None:
    return check_deck(args.check, list_name, cards)

  if args.format == "json":
    payload = {
      "list": list_name,
      "format": "tcg" if is_tcg else "ocg",
      "source": source,
      "cards": [
        {"passcode": passcode, "limit": limit, "name": name}
        for passcode, (limit, name) in sorted(cards.items())
      ],
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
  elif args.format == "csv":
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["passcode", "limit", "name"])
    for passcode, (limit, name) in sorted(cards.items()):
      writer.writerow([passcode, limit, name])
    body = buffer.getvalue()
  else:
    body = f"列表：{list_name}（{'TCG' if is_tcg else 'OCG'}）\n{describe(cards)}\n来源：{source}\n"

  if args.output is not None:
    args.output.write_text(body, encoding="utf-8")
    print(f"已写入 {args.output}（{len(cards)} 张）")
  else:
    sys.stdout.write(body)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
