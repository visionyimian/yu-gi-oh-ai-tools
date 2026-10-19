"""Tests for deck-parser 的 hand_matrix（起手穷举与死手率自检）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "deck-parser" / "scripts"))

from combo_scan import normalize_card
from hand_matrix import build_rules, enumerate_hands, render, resolve_predicate


def card(name, count=1, atk=1000, level=4, section="main", types="怪兽卡|效果", desc=""):
  return normalize_card(
    {
      "name": name,
      "desc": desc,
      "atk": atk,
      "def": 1000,
      "level": level,
      "race": "电子界",
      "attribute": "暗",
      "type": types,
      "archetypes": "",
      "count": count,
    },
    section,
  )


def deck(main, extra=None):
  return {"main": list(main), "extra": list(extra or []), "side": []}


class TestEnumerateHands:
  """穷举结果的正确性。"""

  def test_exact_small_deck(self):
    """6 张卡取 2 张：A 有 2 张、B 有 2 张、C 有 2 张。"""
    d = deck([card("A", 2), card("B", 2), card("C", 2)])
    rules = build_rules(
      {
        "one_card": [{"label": "A单卡", "cards": ["A"]}],
        "two_card": [{"label": "B+C", "first": ["B"], "second": ["C"]}],
      },
      d,
    )
    result = enumerate_hands(d, rules, hand_size=2)

    assert result["total_hands"] == 15
    assert result["one_card"]["rate"] == 60.0  # 9/15
    assert result["two_card"]["rate"] == pytest.approx(26.67, abs=0.01)  # 4/15
    assert result["dead"]["rate"] == pytest.approx(13.33, abs=0.01)  # B+B、C+C
    assert result["startable"] + result["dead"]["rate"] == pytest.approx(100.0, abs=0.01)

  def test_rates_sum_to_total_hands(self):
    d = deck([card("A", 3), card("B", 2), card("C", 2), card("D", 1)])
    rules = build_rules(
      {"one_card": [{"label": "A", "cards": ["A"]}]},
      d,
    )
    result = enumerate_hands(d, rules, hand_size=3)
    assert result["one_card"]["rate"] + result["dead"]["rate"] == pytest.approx(100.0, abs=0.01)

  def test_same_physical_card_cannot_fill_both_slots(self):
    """X 同时出现在 first 与 second 时，手里只有 1 张 X 不能算「两张」。"""
    d = deck([card("X", 1), card("Y", 1), card("Z", 4, atk=1500)])
    rules = build_rules(
      {"two_card": [{"label": "X+Y", "first": ["X"], "second": ["X", "Y"]}]},
      d,
    )
    result = enumerate_hands(d, rules, hand_size=2)
    # 只有 X+Y 这一种组合成立（1/15）
    assert result["two_card"]["rate"] == pytest.approx(6.67, abs=0.01)

  def test_two_copies_can_fill_both_slots(self):
    """手里有 2 张同名卡时，可以分别充当 first 与 second。"""
    d = deck([card("X", 2), card("Z", 4, atk=1500)])
    rules = build_rules(
      {"two_card": [{"label": "X+X", "first": ["X"], "second": ["X"]}]},
      d,
    )
    result = enumerate_hands(d, rules, hand_size=2)
    assert result["two_card"]["rate"] == pytest.approx(6.67, abs=0.01)  # 1/15

  def test_label_buckets_do_not_mix(self):
    d = deck([card("A", 2), card("B", 2), card("C", 2)])
    rules = build_rules(
      {
        "one_card": [{"label": "A单卡", "cards": ["A"]}],
        "two_card": [{"label": "B+C", "first": ["B"], "second": ["C"]}],
      },
      d,
    )
    result = enumerate_hands(d, rules, hand_size=2)
    assert set(result["one_card"]["by_label"]) == {"A单卡"}
    assert set(result["two_card"]["by_label"]) == {"B+C"}

  def test_empty_main_deck_raises(self):
    with pytest.raises(ValueError):
      enumerate_hands(deck([]), [], hand_size=5)


class TestPredicate:
  """谓词展开。"""

  def test_link1_material_predicate(self):
    d = deck(
      [card("低攻", atk=900), card("高攻", atk=1500)],
      extra=[
        card(
          "独角兔",
          section="extra",
          types="怪兽卡|效果|连接",
          level=1,
          desc="通常召唤的攻击力1000以下的怪兽1只",
        )
      ],
    )
    assert resolve_predicate("link1_material", d) == {"低攻"}

  def test_two_card_rule_with_predicate(self):
    d = deck(
      [card("引擎", 1), card("身体", 1, atk=900), card("杂牌", 4, atk=1500)],
      extra=[
        card(
          "独角兔",
          section="extra",
          types="怪兽卡|效果|连接",
          level=1,
          desc="通常召唤的攻击力1000以下的怪兽1只",
        )
      ],
    )
    rules = build_rules(
      {
        "two_card": [
          {"label": "引擎+身体", "first": ["引擎"], "second_predicate": "link1_material"}
        ]
      },
      d,
    )
    result = enumerate_hands(d, rules, hand_size=2)
    assert result["two_card"]["rate"] == pytest.approx(6.67, abs=0.01)

  def test_unknown_predicate_raises(self):
    with pytest.raises(ValueError):
      resolve_predicate("nope", deck([card("A")]))


class TestBuildRulesValidation:
  """规则文件校验。"""

  def test_unknown_card_name_raises(self):
    d = deck([card("A", 3)])
    with pytest.raises(ValueError) as exc:
      build_rules({"one_card": [{"label": "x", "cards": ["不存在的卡"]}]}, d)
    assert "不存在的卡" in str(exc.value)

  def test_missing_second_selector_raises(self):
    d = deck([card("A", 3)])
    with pytest.raises(ValueError):
      build_rules({"two_card": [{"label": "x", "first": ["A"]}]}, d)


class TestRender:
  """摘要输出与死手率告警。"""

  def result(self, dead_rate):
    return {
      "deck_size": 40,
      "hand_size": 5,
      "total_hands": 658008,
      "one_card": {"rate": 100 - dead_rate, "by_label": {"A": 100 - dead_rate}},
      "two_card": {"rate": 0.0, "by_label": {}},
      "startable": 100 - dead_rate,
      "dead": {"rate": dead_rate, "hands": 0, "examples": [{"cards": ["A", "B"], "hands": 1}]},
    }

  def test_warns_above_threshold(self):
    text = render(self.result(20.0), 15.0)
    assert "⚠" in text
    assert "20.00%" in text

  def test_no_warning_below_threshold(self):
    text = render(self.result(5.0), 15.0)
    assert "⚠" not in text
