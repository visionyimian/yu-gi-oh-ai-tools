#!/usr/bin/env python3
"""一条命令跑完分析流程的所有校验。

流水线现在有五个可执行校验，但它们分散在不同步骤里，每次交付都要记一堆命令和参数。
这个脚本把它们串起来，并按组报告结果：

1. **产物完整性** —— 该有的文件在不在、是不是空文件
2. **流程完成度** —— `TODO.md` 里有没有没勾掉的步骤
3. **Step 4.5 一致性** —— 调用 `check_parse.py`（4 项）
4. **Step 5.5 报告一致性** —— 调用 `check_report.py`

只读本地产物，不联网。禁限校验（`ocg-banlist`）需要联网拉取 `lflist.conf`，
所以不在这里重跑——它的结论由 `banlist_check.txt` 是否已生成来体现。

用法::

    python verify.py {analysis} --cdb cards.cdb
    python verify.py {analysis} --cdb cards.cdb --skip-report   # 报告还没写
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path

import check_parse
import check_report

REQUIRED = (
  "banlist_check.txt",
  "deck_raw.csv",
  "deck_raw.json",
  "script_facts.json",
  "combo_candidates.json",
  "combos.json",
  "hand_matrix.json",
  "deck_parsed.json",
  "deck_analysis.json",
  "report.md",
  "TODO.md",
)

PARSE_INPUTS = ("deck_parsed.json", "deck_analysis.json", "hand_matrix.json", "script_facts.json")


def capture(func, argv: list[str]) -> tuple[bool, str]:
  """跑一个子校验并把它的输出抓下来。"""
  buffer = io.StringIO()
  with contextlib.redirect_stdout(buffer):
    code = func(argv)
  return code == 0, buffer.getvalue().rstrip()


def check_artifacts(directory: Path, skip_report: bool) -> tuple[bool, str]:
  expected = [name for name in REQUIRED if not (skip_report and name == "report.md")]
  missing = [
    name
    for name in expected
    if not (directory / name).is_file() or (directory / name).stat().st_size == 0
  ]
  if missing:
    return False, f"缺 {len(missing)} 个：{', '.join(missing)}"
  return True, f"{len(expected)} 个产物齐全"


def check_todo(directory: Path) -> tuple[bool, str]:
  path = directory / "TODO.md"
  pending = [
    line.strip() for line in path.read_text(encoding="utf-8").splitlines() if "- [ ]" in line
  ]
  if pending:
    return False, f"{len(pending)} 项未完成：" + "；".join(item[6:] for item in pending[:3])
  return True, "全部步骤已勾选"


def section(title: str) -> None:
  print(f"\n=== {title} ===")


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="一条命令跑完分析流程的所有校验。")
  parser.add_argument("analysis_dir", type=Path, help="{deck}_analysis 目录")
  parser.add_argument("--cdb", type=Path, required=True, help="cards.cdb（check_parse 需要）")
  parser.add_argument("--skip-report", action="store_true", help="报告尚未生成时跳过相关检查")
  parser.add_argument("--skip-todo", action="store_true", help="跳过 TODO.md 完成度检查")
  args = parser.parse_args(argv)

  directory: Path = args.analysis_dir
  if not directory.is_dir():
    print(f"错误：{directory} 不是目录", file=sys.stderr)
    return 1

  print(f"产物目录：{directory}")
  groups: list[tuple[str, bool]] = []

  section("1/4 产物完整性")
  ok, detail = check_artifacts(directory, args.skip_report)
  print(f"[{'PASS' if ok else 'FAIL'}] {detail}")
  groups.append(("产物完整性", ok))

  if args.skip_todo:
    section("2/4 流程完成度")
    print("[SKIP] 已按参数跳过")
  else:
    section("2/4 流程完成度（TODO.md）")
    ok, detail = check_todo(directory)
    print(f"[{'PASS' if ok else 'FAIL'}] {detail}")
    groups.append(("流程完成度", ok))

  section("3/4 Step 4.5 一致性（check_parse）")
  if all((directory / name).is_file() for name in PARSE_INPUTS):
    sub_argv = [
      "--parsed",
      str(directory / "deck_parsed.json"),
      "--analysis",
      str(directory / "deck_analysis.json"),
      "--matrix",
      str(directory / "hand_matrix.json"),
      "--facts",
      str(directory / "script_facts.json"),
      "--cdb",
      str(args.cdb),
    ]
    ok, output = capture(check_parse.main, sub_argv)
    print("\n".join("  " + line for line in output.splitlines()))
    groups.append(("Step 4.5", ok))
  else:
    print("[SKIP] 缺少 check_parse 的输入文件")
    groups.append(("Step 4.5", False))

  section("4/4 Step 5.5 报告一致性（check_report）")
  report = directory / "report.md"
  if args.skip_report or not report.is_file():
    print("[SKIP] 报告尚未生成")
  else:
    sub_argv = [str(directory / "deck_analysis.json"), str(report)]
    ok, output = capture(check_report.main, sub_argv)
    print("\n".join("  " + line for line in output.splitlines()))
    groups.append(("Step 5.5", ok))

  failed = [name for name, ok in groups if not ok]
  print()
  if failed:
    print(f"[VERIFY FAILED] {len(failed)} 组不通过：{', '.join(failed)}")
    return 1
  print(f"[VERIFY PASSED] {len(groups)} 组检查全部通过")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
