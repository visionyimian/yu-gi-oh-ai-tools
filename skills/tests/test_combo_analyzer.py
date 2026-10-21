"""Tests for the combo-analyzer scripts."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "combo-analyzer" / "scripts"))
from combo_coverage import main as coverage_main
from combo_coverage import producing_cards
from effects_draft import NUMERALS, build


def deck() -> dict:
  return {
    "main": [
      {"name": "白兔", "count": 3, "type": "怪兽卡|效果"},
      {"name": "睡鼠", "count": 1, "type": "怪兽卡|效果"},
      {"name": "灰流丽", "count": 2, "type": "怪兽卡|效果"},
    ],
    "extra": [{"name": "毒蜥", "count": 1, "type": "怪兽卡|效果|连接"}],
    "side": [],
  }


def facts() -> dict:
  return {
    "cards": [
      {
        "id": 1,
        "effects": [
          {
            "kind": "trigger_optional",
            "event": "EVENT_SUMMON_SUCCESS",
            "categories": ["CATEGORY_SSET"],
            "opt": "card_name",
          },
          {
            "kind": "trigger_optional",
            "event": "EVENT_REMOVE",
            "categories": ["CATEGORY_SPECIAL_SUMMON"],
            "opt": "card_name",
          },
        ],
      },
      {
        "id": 2,
        "effects": [
          {"kind": "ignition", "event": "", "categories": ["CATEGORY_REMOVE"], "opt": "card_name"},
        ],
      },
      {
        "id": 3,
        "effects": [
          {
            "kind": "quick_optional",
            "event": "",
            "categories": ["CATEGORY_DRAW"],
            "opt": "card_name",
          },
        ],
      },
    ],
    "missing": [],
    "vanilla": [],
  }


def test_draft_lists_every_script_effect():
  result = build(deck(), facts(), {1: "白兔", 2: "睡鼠", 3: "灰流丽"})

  assert [(e["card"], e["effect"]) for e in result["effects"]] == [
    ("白兔", "①"),
    ("白兔", "②"),
    ("睡鼠", "①"),
    ("灰流丽", "①"),
  ]


def test_draft_leaves_delta_for_a_human():
  result = build(deck(), facts(), {1: "白兔", 2: "睡鼠", 3: "灰流丽"})

  assert all(entry["delta"] is None for entry in result["effects"])
  assert all(entry["requires"] == "" for entry in result["effects"])


def test_draft_skips_cards_without_facts():
  """通常怪兽没有脚本，不应该出现在声明里。"""
  data = deck()
  data["main"].append({"name": "青眼白龙", "count": 1, "type": "怪兽卡|通常"})

  result = build(data, facts(), {1: "白兔", 2: "睡鼠", 3: "灰流丽"})

  assert "青眼白龙" not in [e["card"] for e in result["effects"]]


def test_draft_covers_extra_deck_only_when_listed_in_main():
  """当前只扫主卡组——额外卡组的效果不会自动进来。"""
  result = build(deck(), facts(), {1: "白兔", 2: "睡鼠", 3: "灰流丽"})

  assert "毒蜥" not in [e["card"] for e in result["effects"]]


def test_numerals_cover_ten():
  assert NUMERALS[0] == "①"
  assert NUMERALS[9] == "⑩"


def test_producing_cards_filters_by_category():
  effects = {
    "effects": [
      {"card": "白兔", "categories": ["CATEGORY_SSET"]},
      {"card": "白兔", "categories": ["CATEGORY_SPECIAL_SUMMON"]},
      {"card": "灰流丽", "categories": ["CATEGORY_SEARCH"]},
      {"card": "睡鼠", "categories": ["CATEGORY_REMOVE"]},
    ]
  }

  result = producing_cards(effects)

  assert result == {
    "白兔": ["CATEGORY_SPECIAL_SUMMON", "CATEGORY_SSET"],
    "灰流丽": ["CATEGORY_SEARCH"],
  }


def write_inputs(tmp_path: Path) -> tuple[Path, Path]:
  effects = {
    "effects": [
      {"card": "白兔", "effect": "①", "categories": ["CATEGORY_SSET"]},
      {"card": "星球改造", "effect": "①", "categories": ["CATEGORY_SEARCH"]},
    ]
  }
  analysis = {
    "combo_lines": [
      {"name": "线A", "cards_used": ["白兔"]},
    ]
  }
  e, a = tmp_path / "effects.json", tmp_path / "analysis.json"
  e.write_text(json.dumps(effects, ensure_ascii=False), encoding="utf-8")
  a.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
  return e, a


def test_coverage_reports_unused_producing_card(tmp_path, capsys):
  e, a = write_inputs(tmp_path)

  assert coverage_main([str(e), str(a)]) == 0

  out = capsys.readouterr().out
  assert "星球改造" in out
  assert "白兔" in out


def test_coverage_strict_fails_on_gap(tmp_path):
  e, a = write_inputs(tmp_path)

  assert coverage_main([str(e), str(a), "--strict"]) == 1


def test_coverage_passes_when_everything_is_used(tmp_path, capsys):
  e, a = write_inputs(tmp_path)
  analysis = json.loads(a.read_text(encoding="utf-8"))
  analysis["combo_lines"][0]["cards_used"].append("星球改造")
  a.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

  assert coverage_main([str(e), str(a), "--strict"]) == 0
  assert "都至少出现在一条做场线里" in capsys.readouterr().out
