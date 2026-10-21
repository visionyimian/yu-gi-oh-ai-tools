#!/usr/bin/env python3
"""从 `analyses` 分支把某副牌的分析产物取回到本地目录。

分析产物不进 `main`（会污染 diff），但模拟器又要读它们。这个脚本是两者之间的桥：

    python fetch_analysis.py --deck 奥艺码丽丝
    python fetch_analysis.py --deck 奥艺码丽丝 --out D:/work/decks/奥艺码丽丝_analysis
    python fetch_analysis.py --list

它用 `git show <rev>:<path>` 直接取 blob 的**原始字节**写入文件，
不经过 PowerShell 的编码转换——否则中文 JSON 会被加上 BOM 或者改成 CRLF。
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> bytes:
  result = subprocess.run(
    ["git", "-C", str(repo), *args],
    capture_output=True,
    check=False,
  )
  if result.returncode != 0:
    message = result.stderr.decode("utf-8", "replace").strip()
    raise SystemExit(f"git {' '.join(args)} 失败：{message}")
  return result.stdout


def list_decks(repo: Path, rev: str) -> list[str]:
  tree = git(repo, "ls-tree", "-r", "--name-only", rev, "--", "analyses/")
  names = set()
  for line in tree.decode("utf-8").splitlines():
    parts = line.split("/")
    if len(parts) >= 3:
      names.add(parts[1])
  return sorted(names)


def fetch(repo: Path, rev: str, deck: str, out: Path) -> int:
  prefix = f"analyses/{deck}/"
  tree = git(repo, "ls-tree", "-r", "--name-only", rev, "--", prefix)
  files = [line for line in tree.decode("utf-8").splitlines() if line.startswith(prefix)]
  if not files:
    raise SystemExit(f"{rev} 上没有 {prefix} —— 用 --list 看看有哪些")

  out.mkdir(parents=True, exist_ok=True)
  for path in files:
    relative = path[len(prefix) :]
    target = out / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(git(repo, "show", f"{rev}:{path}"))
    print(f"  {relative}")
  return len(files)


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="从 analyses 分支取回分析产物。")
  parser.add_argument("--deck", help="卡组目录名，例如 奥艺码丽丝")
  parser.add_argument("--out", type=Path, help="输出目录，默认 ./<deck>_analysis")
  parser.add_argument("--rev", default="origin/analyses", help="分支名（默认 origin/analyses）")
  parser.add_argument(
    "--repo",
    type=Path,
    default=Path(__file__).resolve().parents[4],
    help="仓库路径，默认自动推断",
  )
  parser.add_argument("--list", action="store_true", help="列出分支上有哪些卡组")
  args = parser.parse_args(argv)

  repo = args.repo
  if args.list or not args.deck:
    decks = list_decks(repo, args.rev)
    print(f"{args.rev} 上有 {len(decks)} 副：")
    for deck in decks:
      print(f"  {deck}")
    return 0

  out = args.out or Path(f"{args.deck}_analysis")
  count = fetch(repo, args.rev, args.deck, out)
  print(f"已取回 {count} 个文件 -> {out}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
