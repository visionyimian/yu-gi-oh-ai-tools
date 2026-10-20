"""Tests for the Step 4.5 checker."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "ygo-deck-analyze" / "scripts"))
from check_parse import main


def build(tmp_path: Path, **overrides) -> list[str]:
  """写一套一致的产物，再按需破坏其中一处。"""
  cdb = tmp_path / "cards.cdb"
  connection = sqlite3.connect(cdb)
  connection.execute("CREATE TABLE texts (id INTEGER PRIMARY KEY, name TEXT)")
  connection.execute("INSERT INTO texts VALUES (1, '卡A')")
  connection.commit()
  connection.close()

  effects = [
    {"kind": "trigger_optional", "targets": False, "has_cost": True, "no_miss_timing": True}
  ]
  facts = {
    "cards": [
      {
        "id": 1,
        "opt": overrides.get("opt", "card_name_once"),
        "restrictions": [],
        "indirect_restrictions": [],
        "effects": effects,
      }
    ],
    "missing": [],
    "vanilla": [],
  }

  card = {
    "name": "卡A",
    "copies": 1,
    "types": ["starter"],
    "once_per_turn_type": overrides.get("type", "card_name_once"),
    "once_per_turn_source": overrides.get("source", "script"),
    "script": overrides.get(
      "block",
      {"kinds": ["trigger_optional"], "targets": False, "has_cost": True, "no_miss_timing": True},
    ),
  }
  if card["script"] is None:
    del card["script"]

  matrix = {
    "hand_size": 5,
    "total_hands": 100,
    "startable": overrides.get("startable", 93.25),
    "dead": {"rate": 6.75, "over_threshold": False},
  }
  parsed = {
    "engines": [{"name": "E", "role": "primary", "cards": [card]}],
    "starters": {"cards": [], "total_copies": 1},
    "extenders": {"cards": [], "total_copies": 0},
    "handtraps": {"cards": [], "total_copies": 0},
    "extradeck_monsters": [],
    "maindeck_endboard": [{"name": "卡A", "copies": 1}],
    "hand_matrix": {
      "hand_size": 5,
      "total_hands": 100,
      "startable_rate": overrides.get("recorded", "93.25%"),
      "dead_rate": "6.75%",
      "dead_over_threshold": False,
    },
  }
  analysis = {
    "first_turn_board": {
      "typical_endboard": []
      if overrides.get("no_endboard")
      else [{"card_name": "卡A", "role": "x"}]
    }
  }

  paths = []
  for name, data in (
    ("parsed.json", parsed),
    ("analysis.json", analysis),
    ("matrix.json", matrix),
    ("facts.json", facts),
  ):
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    paths.append(str(path))
  paths.append(str(cdb))
  return paths


def run(paths: list[str]) -> int:
  parsed, analysis, matrix, facts, cdb = paths
  return main(
    [
      "--parsed",
      parsed,
      "--analysis",
      analysis,
      "--matrix",
      matrix,
      "--facts",
      facts,
      "--cdb",
      cdb,
    ]
  )


def test_consistent_inputs_pass(tmp_path, capsys):
  assert run(build(tmp_path)) == 0

  out = capsys.readouterr().out
  assert "VALIDATION PASSED" in out


def test_missing_endboard_fails(tmp_path, capsys):
  assert run(build(tmp_path, no_endboard=True)) == 1

  assert "卡A" in capsys.readouterr().out


def test_matrix_mismatch_fails(tmp_path, capsys):
  assert run(build(tmp_path, recorded="80.03%")) == 1

  assert "能动率" in capsys.readouterr().out


def test_custom_without_source_fails(tmp_path, capsys):
  assert run(build(tmp_path, opt="custom", source="script")) == 1

  assert "script_custom" in capsys.readouterr().out


def test_script_block_mismatch_fails(tmp_path, capsys):
  wrong = {"kinds": ["ignition"], "targets": False, "has_cost": True, "no_miss_timing": True}

  assert run(build(tmp_path, block=wrong)) == 1

  assert "kinds" in capsys.readouterr().out


def test_missing_script_block_fails(tmp_path, capsys):
  assert run(build(tmp_path, block=None)) == 1

  assert "缺 script 块" in capsys.readouterr().out
