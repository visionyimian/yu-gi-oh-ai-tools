"""Tests for deck-parser 的 combo_scan（需求 → 满足者联结）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "deck-parser" / "scripts"))

from combo_scan import (
  extract_triggers,
  load_deck,
  match_material,
  normalize_card,
  parse_material,
  scan,
)


def make_card(name, desc="", section="main", types="怪兽卡|效果", **kwargs):
  raw = {
    "name": name,
    "desc": desc,
    "atk": kwargs.get("atk", 1000),
    "def": kwargs.get("def", 1000),
    "level": kwargs.get("level", 4),
    "race": kwargs.get("race", "电子界"),
    "attribute": kwargs.get("attribute", "暗"),
    "type": types,
    "archetypes": kwargs.get("archetypes", ""),
    "count": kwargs.get("count", 1),
  }
  return normalize_card(raw, section)


def make_deck(main, extra=None):
  return {"main": list(main), "extra": list(extra or []), "side": []}


class TestParseMaterial:
  """素材行解析。"""

  def test_normal_summon_atk_gate(self):
    gate = parse_material("通常召唤的攻击力1000以下的怪兽1只")
    assert gate["kind"] == "ns_max_atk"
    assert gate["max_atk"] == 1000
    assert gate["count"] == 1

  def test_race_level_gate(self):
    gate = parse_material("4星以下的电子界族怪兽1只")
    assert gate["kind"] == "race_level"
    assert gate["level"] == 4
    assert gate["race"] == "电子界"

  def test_archetype_gate(self):
    gate = parse_material("包含「码丽丝」怪兽的怪兽3只")
    assert gate["kind"] == "archetype"
    assert gate["archetype"] == "码丽丝"
    assert gate["count"] == 3

  def test_effect_gate(self):
    assert parse_material("效果怪兽2只")["kind"] == "effect"

  def test_unknown_gate_does_not_crash(self):
    assert parse_material("包含融合·同调·超量·连接怪兽的怪兽2只以上")["kind"] == "ed_monster"


class TestMatchMaterial:
  """素材条件匹配。"""

  def test_ns_max_atk_excludes_high_atk_and_special_summon_only(self):
    deck = make_deck(
      [
        make_card("低攻", atk=900),
        make_card("高攻", atk=1500),
        make_card("不能通召", atk=500, types="怪兽卡|效果|特殊召唤"),
      ]
    )
    matched = [c["name"] for c in match_material({"kind": "ns_max_atk", "max_atk": 1000}, deck)]
    assert matched == ["低攻"]

  def test_race_level_gate(self):
    deck = make_deck(
      [
        make_card("三星电子界", level=3, race="电子界"),
        make_card("五星电子界", level=5, race="电子界"),
        make_card("三星战士", level=3, race="战士"),
      ]
    )
    gate = {"kind": "race_level", "level": 4, "race": "电子界"}
    matched = [c["name"] for c in match_material(gate, deck)]
    assert matched == ["三星电子界"]

  def test_archetype_matches_by_name(self):
    deck = make_deck([make_card("码丽丝<兵卒>白兔"), make_card("灰流丽", race="不死")])
    gate = {"kind": "archetype", "archetype": "码丽丝"}
    assert [c["name"] for c in match_material(gate, deck)] == ["码丽丝<兵卒>白兔"]


class TestExtractTriggers:
  """触发条件抽取。"""

  def test_long_trigger_suppresses_contained_short_trigger(self):
    card = make_card(
      "无限",
      desc="②：这张卡是除外状态，融合·连接怪兽特殊召唤的场合才能发动。这张卡特殊召唤。",
    )
    kinds = [t["kind"] for t in extract_triggers(card)]
    assert "fusion_link_summon" in kinds
    assert "link_summon" not in kinds

  def test_self_sent_to_gy_is_skipped(self):
    card = make_card("解码员", desc="①：让这张卡被送去墓地的场合才能发动。这张卡特殊召唤。")
    kinds = [t["kind"] for t in extract_triggers(card)]
    assert "sent_to_gy" not in kinds

  def test_banished_trigger_is_kept(self):
    card = make_card("白兔", desc="③：这张卡被除外的场合，支付300基本分才能发动。这张卡特殊召唤。")
    triggers = extract_triggers(card)
    assert [t["kind"] for t in triggers] == ["banished"]
    assert triggers[0]["self_trigger"] is True


class TestScan:
  """整卡组扫描。"""

  def deck(self):
    return make_deck(
      [
        make_card(
          "无限与有限之无垢大艺术",
          desc="②：这张卡是除外状态，融合·连接怪兽特殊召唤的场合才能发动。这张卡特殊召唤。",
          level=8,
          race="战士",
          atk=1000,
          count=3,
        ),
        make_card("睡鼠", atk=900, level=3),
      ],
      extra=[
        make_card(
          "转生炎兽 独角兔",
          desc="通常召唤的攻击力1000以下的怪兽1只",
          section="extra",
          types="怪兽卡|效果|连接",
          level=1,
          atk=0,
        )
      ],
    )

  def test_finds_link_one_enabler_for_summon_trigger(self):
    report = scan(self.deck())
    trigger = next(t for t in report["triggers"] if t["card"] == "无限与有限之无垢大艺术")
    enablers = [e["card"] for e in trigger["enablers"]]
    assert "转生炎兽 独角兔" in enablers

  def test_reports_material_satisfier_count(self):
    report = scan(self.deck())
    link = next(link for link in report["link_monsters"] if link["name"] == "转生炎兽 独角兔")
    # 睡鼠 900 攻击力满足「通常召唤的攻击力1000以下」；
    # 无限与有限本身是 1000 攻击力，也能作为素材（所以是 1 + 3 = 4）
    assert link["satisfier"]["copies"] == 4

  def test_candidate_pairs_are_emitted(self):
    report = scan(self.deck())
    pairs = {(p["trigger_card"], p["enabler_card"]) for p in report["candidate_pairs"]}
    assert ("无限与有限之无垢大艺术", "转生炎兽 独角兔") in pairs


class TestLoadDeck:
  """输入格式。"""

  def test_loads_json(self, tmp_path):
    path = tmp_path / "deck.json"
    path.write_text(
      '{"main": [{"name": "A", "desc": "", "atk": 100, "level": 1, '
      '"race": "电子界", "attribute": "暗", "type": "怪兽卡|效果", "count": 2}],'
      ' "extra": [], "side": []}',
      encoding="utf-8",
    )
    deck = load_deck(str(path))
    assert deck["main"][0]["name"] == "A"
    assert deck["main"][0]["count"] == 2

  def test_loads_csv_with_multiline_desc(self, tmp_path):
    path = tmp_path / "deck.csv"
    path.write_text(
      "name,desc,atk,def,level,race,attribute,type,setNames,count,deck\n"
      'A,"第一行\n第二行",100,100,1,电子界,暗,怪兽卡|效果,,2,main\n',
      encoding="utf-8",
    )
    deck = load_deck(str(path))
    assert len(deck["main"]) == 1
    assert "第二行" in deck["main"][0]["desc"]
