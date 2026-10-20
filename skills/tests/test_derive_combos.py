"""Tests for the automatic combos.json derivation."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "deck-parser" / "scripts"))
from derive_combos import derive, producing_effects
from hand_matrix import main as hand_matrix_main


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


def test_hand_matrix_can_derive_rules_itself(tmp_path, capsys):
  """--derive 让 hand_matrix 不需要 combos.json 也能跑。"""
  deck, facts, candidates, _, cdb = build(tmp_path)
  # 这套夹具没有额外卡组，把 enabler 换成主卡组的卡，走「按卡名」那条分支
  candidates["triggers"][0]["enablers"] = [{"card": "A"}]
  deck_path = tmp_path / "deck_raw.json"
  deck_path.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
  facts_path = tmp_path / "facts.json"
  facts_path.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
  cand_path = tmp_path / "candidates.json"
  cand_path.write_text(json.dumps(candidates, ensure_ascii=False), encoding="utf-8")
  rules_path = tmp_path / "combos.json"

  code = hand_matrix_main(
    [
      str(deck_path),
      "--derive",
      "--facts",
      str(facts_path),
      "--candidates",
      str(cand_path),
      "--cdb",
      str(cdb),
      "--write-rules",
      str(rules_path),
      "--hand-size",
      "2",
    ]
  )

  assert code == 0
  assert "自动推导动点" in capsys.readouterr().out
  written = json.loads(rules_path.read_text(encoding="utf-8"))
  assert [rule["label"] for rule in written["one_card"]] == ["A单卡", "B单卡"]
  assert [rule["label"] for rule in written["two_card"]] == ["D＋触发件"]


def test_hand_matrix_without_rules_or_derive_reports_an_error(tmp_path, capsys):
  deck, _, _, _, _ = build(tmp_path)
  deck_path = tmp_path / "deck_raw.json"
  deck_path.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")

  assert hand_matrix_main([str(deck_path)]) == 1
  assert "combos.json" in capsys.readouterr().err
