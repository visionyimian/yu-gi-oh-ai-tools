"""Tests for the one-shot verifier."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "ygo-deck-analyze" / "scripts"))
from verify import main


def build(tmp_path: Path) -> tuple[Path, Path]:
  """造一套完整且一致的产物目录，返回 (目录, cdb)。"""
  directory = tmp_path / "deck_analysis"
  directory.mkdir()

  cdb = tmp_path / "cards.cdb"
  connection = sqlite3.connect(cdb)
  connection.execute("CREATE TABLE texts (id INTEGER PRIMARY KEY, name TEXT)")
  connection.execute("INSERT INTO texts VALUES (1, '卡A')")
  connection.commit()
  connection.close()

  facts = {
    "cards": [
      {
        "id": 1,
        "opt": "card_name_once",
        "restrictions": [],
        "indirect_restrictions": [],
        "effects": [
          {"kind": "trigger_optional", "targets": False, "has_cost": True, "no_miss_timing": True}
        ],
      }
    ],
    "missing": [],
    "vanilla": [],
  }
  parsed = {
    "engines": [
      {
        "name": "E",
        "role": "primary",
        "cards": [
          {
            "name": "卡A",
            "copies": 1,
            "types": ["starter"],
            "once_per_turn_type": "card_name_once",
            "once_per_turn_source": "script",
            "script": {
              "kinds": ["trigger_optional"],
              "targets": False,
              "has_cost": True,
              "no_miss_timing": True,
            },
          }
        ],
      }
    ],
    "starters": {"cards": [], "total_copies": 1},
    "extenders": {"cards": [], "total_copies": 0},
    "handtraps": {"cards": [], "total_copies": 0},
    "extradeck_monsters": [],
    "maindeck_endboard": [{"name": "卡A", "copies": 1}],
    "hand_matrix": {
      "hand_size": 5,
      "total_hands": 100,
      "startable_rate": "93.25%",
      "dead_rate": "6.75%",
      "dead_over_threshold": False,
    },
  }
  analysis = {
    "first_turn_board": {"typical_endboard": [{"card_name": "卡A", "role": "x"}]},
  }
  matrix = {"hand_size": 5, "total_hands": 100, "startable": 93.25, "dead": {"rate": 6.75}}

  payloads = {
    "deck_parsed.json": parsed,
    "deck_analysis.json": analysis,
    "hand_matrix.json": matrix,
    "script_facts.json": facts,
    "deck_raw.json": {},
    "combo_candidates.json": {},
    "combos.json": {},
  }
  for name, data in payloads.items():
    (directory / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

  (directory / "banlist_check.txt").write_text("通过\n", encoding="utf-8")
  (directory / "deck_raw.csv").write_text("name\n卡A\n", encoding="utf-8")
  (directory / "report.md").write_text("卡A\n", encoding="utf-8")
  (directory / "TODO.md").write_text("- [x] Step 1.5\n- [x] Step 5\n", encoding="utf-8")
  return directory, cdb


def run(directory: Path, cdb: Path, *extra: str) -> int:
  return main([str(directory), "--cdb", str(cdb), *extra])


def test_complete_run_passes(tmp_path, capsys):
  directory, cdb = build(tmp_path)

  assert run(directory, cdb) == 0

  out = capsys.readouterr().out
  assert "VERIFY PASSED" in out
  assert "4 组检查全部通过" in out


def test_missing_artifact_fails(tmp_path, capsys):
  directory, cdb = build(tmp_path)
  (directory / "combos.json").unlink()

  assert run(directory, cdb) == 1

  assert "combos.json" in capsys.readouterr().out


def test_unfinished_todo_fails(tmp_path, capsys):
  directory, cdb = build(tmp_path)
  (directory / "TODO.md").write_text("- [x] Step 1\n- [ ] Step 5\n", encoding="utf-8")

  assert run(directory, cdb) == 1

  assert "1 项未完成" in capsys.readouterr().out


def test_report_missing_from_report_fails(tmp_path, capsys):
  directory, cdb = build(tmp_path)
  (directory / "report.md").write_text("什么都没写\n", encoding="utf-8")

  assert run(directory, cdb) == 1

  assert "VALIDATION FAILED" in capsys.readouterr().out


def test_skip_report_allows_partial_run(tmp_path, capsys):
  directory, cdb = build(tmp_path)
  (directory / "report.md").unlink()

  assert run(directory, cdb, "--skip-report") == 0

  out = capsys.readouterr().out
  assert "SKIP" in out
  assert "VERIFY PASSED" in out
