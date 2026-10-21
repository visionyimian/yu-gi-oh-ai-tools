"""Tests for the generated ygopro-core constant table."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "combo-analyzer" / "scripts" / "simulator"))
import ocg_constants as c
from gen_constants import parse

SMALL_HEADER = """#define LOCATION_DECK 0x01
#define LOCATION_HAND 0x02
#define LOCATION_ONFIELD (LOCATION_DECK | LOCATION_HAND)
#define TYPE_MONSTER 0x1
#define TYPE_LINK 0x4000000
#define BROKEN undefined_name_here
"""


def test_key_values_match_upstream():
  """这几个值直接决定协议解析能不能对上。"""
  assert c.MSG_SELECT_IDLECMD == 11
  assert c.MSG_SELECT_CHAIN == 16
  assert c.MSG_NEW_TURN == 40
  assert c.TYPE_LINK == 0x4000000
  assert c.LOCATION_DECK == 0x01
  assert c.LOCATION_ONFIELD == 0x0C
  assert c.RACE_CYBERSE == 0x1000000
  assert c.ATTRIBUTE_DARK == 0x20
  assert c.QUERY_END == 0x80000000
  assert c.PHASE_MAIN1 == 0x04


def test_tables_map_values_back_to_names():
  assert c.LOCATIONS[0x01] == "LOCATION_DECK"
  assert c.MESSAGES[11] == "MSG_SELECT_IDLECMD"
  assert c.TYPES[0x4000000] == "TYPE_LINK"


def test_describe_splits_into_single_bits():
  assert c.describe(c.LOCATION_MZONE | c.LOCATION_SZONE, c.LOCATIONS) == (
    "LOCATION_MZONE|LOCATION_SZONE (LOCATION_ONFIELD)"
  )


def test_describe_handles_unknown_value():
  assert c.describe(0, c.LOCATIONS) == "0x0"


def test_parse_resolves_compound_defines():
  values = parse(SMALL_HEADER)

  assert values["LOCATION_DECK"] == 1
  assert values["LOCATION_ONFIELD"] == 3
  assert values["TYPE_LINK"] == 0x4000000


def test_parse_skips_expressions_it_cannot_resolve():
  values = parse(SMALL_HEADER)

  assert "BROKEN" not in values
