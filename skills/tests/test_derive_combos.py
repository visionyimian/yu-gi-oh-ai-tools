"""Tests for the automatic combos.json derivation."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "deck-parser" / "scripts"))
from derive_combos import derive, producing_effects


def build(tmp_path: Path) -> tuple[dict, dict, dict, dict, Path]:
  cdb = tmp_path / "cards.cdb"
  connection = sqlite3.connect(cdb)
  connection.execute("CREATE TABLE texts (id INTEGER PRIMARY KEY, name TEXT)")
  for index, name in enumerate(("A", "B", "C", "D"), start=1):
    connection.execute("INSERT INTO texts VALUES (?, ?)", (index, name))
  connection.commit()
  connection.close()

  deck = {
    "main": [
      {"name": "A", "type": "怪兽卡|效果", "count": 3},
      {"name": "B", "type": "魔法卡", "count": 1},
      {"name": "C", "type": "陷阱卡", "count": 1},
      {"name": "D", "type": "怪兽卡|效果", "count": 2},
    ],
    "extra": [],
    "side": [],
  }
  facts = {
    "cards": [
      {"id": 1, "effects": [{"kind": "ignition", "categories": ["CATEGORY_SEARCH"]}]},
      {"id": 2, "effects": [{"kind": "activation", "categories": ["CATEGORY_SPECIAL_SUMMON"]}]},
      {"id": 3, "effects": [{"kind": "activation", "categories": ["CATEGORY_SEARCH"]}]},
      {"id": 4, "effects": []},
    ]
  }
  candidates = {
    "triggers": [
      {
        "card": "D",
        "self_trigger": False,
        "text": "连接怪兽特殊召唤的场合",
        "enablers": [{"card": "L1", "link_rating": 1}, {"card": "L2", "link_rating": 2}],
      }
    ]
  }
  names = {1: "A", 2: "B", 3: "C", 4: "D"}
  return deck, facts, candidates, names, cdb


def test_producing_effects_requires_category_and_kind():
  effect = {"kind": "ignition", "categories": ["CATEGORY_SEARCH"]}
  assert producing_effects({"effects": [effect]}) == [effect]
  assert (
    producing_effects({"effects": [{"kind": "ignition", "categories": ["CATEGORY_DRAW"]}]}) == []
  )
  assert (
    producing_effects({"effects": [{"kind": "continuous", "categories": ["CATEGORY_SEARCH"]}]})
    == []
  )


def test_traps_are_not_one_card_starters(tmp_path):
  deck, facts, candidates, names, _ = build(tmp_path)

  result = derive(deck, facts, candidates, names)
  labels = [rule["label"] for rule in result["one_card"]]

  assert "A单卡" in labels
  assert "B单卡" in labels
  assert "C单卡" not in labels  # 陷阱卡不能先手单独启动


def test_external_trigger_becomes_a_two_card_rule(tmp_path):
  deck, facts, candidates, names, _ = build(tmp_path)

  result = derive(deck, facts, candidates, names)

  assert [rule["label"] for rule in result["two_card"]] == ["D＋触发件"]
  rule = result["two_card"][0]
  assert rule["first"] == ["D"]
  assert rule["second_predicate"] == "link1_material"  # 取最便宜的那个
  assert result["derivation"]["deferred_to_two_card"] == ["D"]


def test_rules_carry_a_reason(tmp_path):
  deck, facts, candidates, names, _ = build(tmp_path)

  result = derive(deck, facts, candidates, names)

  assert all(rule["reason"] for rule in result["one_card"] + result["two_card"])
