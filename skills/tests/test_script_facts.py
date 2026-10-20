"""Tests for the script_facts parser (synthetic fixtures, no network)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "deck-parser" / "scripts"))
from script_facts import main, parse_card, read_ydk_ids, summarize_opt


FIXTURES = Path(__file__).parent / "fixtures" / "scripts"


def load(name: str) -> dict:
  return parse_card((FIXTURES / name).read_text(encoding="utf-8"))


def test_trigger_delay_card_name_limit_and_cost():
  """A delayed trigger limited by card name, with a cost."""
  facts = load("c10000001.lua")
  effect = facts["effects"][0]

  assert effect["kind"] == "trigger_optional"
  assert effect["event"] == "EVENT_SUMMON_SUCCESS"
  assert effect["opt"] == "card_name"
  assert effect["no_miss_timing"] is True
  assert effect["has_cost"] is True
  assert effect["targets"] is False
  assert summarize_opt(facts) == "card_name_once"


def test_ignition_without_limit_takes_target():
  """Legacy `c<id>.initial_effect` entry style; ignition, no limit, takes a target."""
  facts = load("c10000002.lua")
  effect = facts["effects"][0]

  assert effect["kind"] == "ignition"
  assert effect["opt"] == "none"
  assert effect["targets"] is True
  assert effect["has_cost"] is False
  assert summarize_opt(facts) == "unlimited"


def test_clone_inherits_and_overrides():
  """A cloned effect keeps the source declarations until it overrides them."""
  facts = load("c10000003.lua")

  assert len(facts["effects"]) == 2
  first, second = facts["effects"]
  assert first["opt"] == "card"
  assert second["cloned_from"] == 1
  assert second["opt"] == "card"
  assert second["event"] == "EVENT_TO_GRAVE"


def test_quick_effect_and_restriction():
  facts = load("c10000004.lua")

  assert facts["effects"][0]["kind"] == "quick_optional"
  assert facts["effects"][0]["opt"] == "card_name"
  assert "EFFECT_CANNOT_SPECIAL_SUMMON" in facts["restrictions"]
  assert facts["indirect_restrictions"] == []


def test_restriction_applied_at_resolution_is_indirect():
  """A lock registered inside a helper function is reported separately."""
  facts = load("c10000005.lua")

  assert facts["restrictions"] == []
  assert "EFFECT_CANNOT_SPECIAL_SUMMON" in facts["indirect_restrictions"]


def test_flag_based_limit_is_custom_not_unlimited():
  """No SetCountLimit, but a flag counter: must not be reported as unlimited."""
  facts = load("c10000006.lua")

  assert facts["custom_opt"] is True
  assert summarize_opt(facts) == "custom"
  assert facts["custom_evidence"]["aux_helpers"] == ["EnableGlobalCheck"]
  assert any("GetFlagEffect" in check for check in facts["custom_evidence"]["flag_checks"])


def test_helper_functions_are_not_parsed():
  """Effects created inside helper functions must not leak into the card's list."""
  text = (FIXTURES / "c10000001.lua").read_text(encoding="utf-8")
  facts = parse_card(text)

  assert len(facts["effects"]) == 1


def test_read_ydk_ids_dedupes_and_skips_markers(tmp_path):
  deck = tmp_path / "deck.ydk"
  deck.write_text(
    "#created by test\r\n#main\r\n10000001\r\n10000001\r\n#extra\r\n10000002\r\n!side\r\n",
    encoding="utf-8",
  )

  assert read_ydk_ids(deck) == [10000001, 10000002]


def test_offline_run_reports_missing(tmp_path, capsys):
  out = tmp_path / "facts.json"

  assert main([
    "--ids", "10000001", "99999999",
    "--cache", str(FIXTURES),
    "--offline",
    "-o", str(out),
  ]) == 0

  payload = json.loads(out.read_text(encoding="utf-8"))
  assert [card["id"] for card in payload["cards"]] == [10000001]
  assert payload["missing"] == [99999999]
