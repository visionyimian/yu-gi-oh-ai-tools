"""Tests for the report coverage checker."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "ygo-deck-analyze" / "scripts"))
from check_report import collect, main


def analysis() -> dict:
  return {
    "first_turn_board": {"typical_endboard": [{"card_name": "白棋捆绑", "role": "盖放陷阱"}]},
    "endboard_vulnerability": {
      "board_breaker_threats": [{"threat": "羽毛扫"}, {"threat": "冥王结界波"}]
    },
    "handtrap_vulnerability": {"analysis": [{"handtrap": "灰流丽"}]},
    "chokepoints": [{"card_involved": "红心加密"}],
    "going_second": {"board_breaking_tools": [{"card": "颉颃胜负"}]},
    "score": {"consistency": {"value": 9}, "ceiling": {"value": 8}},
  }


def write(tmp_path: Path, text: str) -> tuple[Path, Path]:
  a = tmp_path / "analysis.json"
  a.write_text(json.dumps(analysis(), ensure_ascii=False), encoding="utf-8")
  r = tmp_path / "report.md"
  r.write_text(text, encoding="utf-8")
  return a, r


def test_collect_extracts_identifiers():
  items = collect(analysis())

  assert ("终场卡片", "白棋捆绑") in items
  assert ("盘面突破", "冥王结界波") in items
  assert ("六维评分", "consistency") in items
  assert len(items) == 8


def test_complete_report_passes(tmp_path, capsys):
  a, r = write(
    tmp_path,
    "白棋捆绑 / 羽毛扫 / 冥王结界波 / 灰流丽 / 红心加密 / 颉颃胜负 / consistency / ceiling",
  )

  assert main([str(a), str(r)]) == 0
  assert "VALIDATION PASSED" in capsys.readouterr().out


def test_missing_row_fails_and_names_it(tmp_path, capsys):
  a, r = write(
    tmp_path,
    "白棋捆绑 / 羽毛扫 / 灰流丽 / 红心加密 / 颉颃胜负 / consistency / ceiling",
  )

  assert main([str(a), str(r)]) == 1

  out = capsys.readouterr().out
  assert "冥王结界波" in out
  assert "VALIDATION FAILED" in out


def test_empty_analysis_is_an_error(tmp_path):
  a = tmp_path / "analysis.json"
  a.write_text("{}", encoding="utf-8")
  r = tmp_path / "report.md"
  r.write_text("nothing", encoding="utf-8")

  assert main([str(a), str(r)]) == 1
