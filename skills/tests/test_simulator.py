"""Tests for the engine-driven combo simulator's pure-python parts."""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "combo-analyzer" / "scripts" / "simulator"))
import field_model as f
import messages as msg
from m5d import short_name


def card_bytes(code: int, sequence: int, location: int = 0x04) -> bytes:
  """一条 SELECT_UNSELECT 列表项：code + ctrl/loc + seq + pos。"""
  return struct.pack("<IBBII", code, 0, location, sequence, 0x1)


def select_unselect_payload(select: list[bytes], unselect: list[bytes] | None = None) -> bytes:
  unselect = unselect or []
  payload = struct.pack("<BBBII", 0, 1, 1, 1, 2)
  payload += struct.pack("<I", len(select)) + b"".join(select)
  payload += struct.pack("<I", len(unselect)) + b"".join(unselect)
  return payload


def test_linked_zones_from_extra_monster_zone():
  """小男巫（↓ ↘）站左额外怪兽区，指着主要怪兽区 1 和 2。"""
  marker = f.LINK_MARKER_BOTTOM | f.LINK_MARKER_BOTTOM_RIGHT

  assert f.linked_zones(5, marker) == {1, 2}
  assert f.linked_zones(6, marker) == {3, 4}


def test_linked_zones_from_main_monster_zone():
  """站主要怪兽区时左右箭头连相邻格，朝下的箭头只落到魔陷区。"""
  assert f.linked_zones(2, f.LINK_MARKER_LEFT | f.LINK_MARKER_RIGHT) == {1, 3}
  assert f.linked_zones(0, f.LINK_MARKER_BOTTOM) == set()


def test_linked_zones_edge_cases():
  assert f.linked_zones(0, f.LINK_MARKER_LEFT) == set()
  assert f.linked_zones(4, f.LINK_MARKER_RIGHT) == set()
  # 站在主要怪兽区朝上指时，只有正对着的额外怪兽区算数（照抄 card::get_linked_zone）
  assert f.linked_zones(1, f.LINK_MARKER_TOP) == {5}
  assert f.linked_zones(3, f.LINK_MARKER_TOP) == {6}
  assert f.linked_zones(2, f.LINK_MARKER_TOP_RIGHT) == {6}


class FakeDeck:
  """只提供 Field 需要的两个接口。"""

  def __init__(self, markers: dict[int, int] | None = None):
    self.marker_table = markers or {}
    self.names = {code: f"card{code}" for code in self.marker_table}

  def markers(self, code: int) -> int:
    return self.marker_table.get(code, 0)


def test_choose_zone_prefers_linked_square():
  deck = FakeDeck({10: f.LINK_MARKER_BOTTOM | f.LINK_MARKER_BOTTOM_RIGHT})
  field = f.Field(deck)
  field.place(5, 10)

  assert field.linked() == {1, 2}
  assert field.choose_zone([0, 1, 2, 3, 4]) == 1
  assert field.choose_zone([0, 3, 4]) == 0


def test_choose_zone_prefers_extra_monster_zone():
  field = f.Field(FakeDeck())
  field.place(0, 99)

  assert field.choose_zone([0, 1, 2, 3, 4, 5, 6]) == 5
  assert field.choose_zone([1, 2]) == 1
  assert field.choose_zone([8, 9]) == 8


def test_field_tracks_moves():
  field = f.Field(FakeDeck({10: f.LINK_MARKER_BOTTOM}))
  move = {
    "code": 10,
    "from": {"controller": 0, "location": 0x40, "sequence": 12},
    "to": {"controller": 0, "location": 0x04, "sequence": 5},
  }

  field.update_from_move(move)
  assert field.monsters == {5: 10}

  field.update_from_move({**move, "from": move["to"], "to": move["from"]})
  assert field.monsters == {}


def test_field_ignores_opponent_moves():
  field = f.Field(FakeDeck())
  field.update_from_move(
    {
      "code": 10,
      "from": {"controller": 1, "location": 0x01, "sequence": 0},
      "to": {"controller": 1, "location": 0x04, "sequence": 0},
    }
  )

  assert field.monsters == {}


def test_decode_select_unselect_card():
  message = msg.Message(
    type=0,
    payload=select_unselect_payload([card_bytes(32061192, 0), card_bytes(69272449, 2)]),
  )
  decoded = msg.decode_select_unselect_card(message)

  assert decoded["player"] == 0
  assert (decoded["min"], decoded["max"]) == (1, 2)
  assert [card["code"] for card in decoded["select"]] == [32061192, 69272449]
  assert [card["sequence"] for card in decoded["select"]] == [0, 2]
  assert decoded["unselect"] == []


def test_decode_select_unselect_card_with_unselect_list():
  message = msg.Message(
    type=0,
    payload=select_unselect_payload([card_bytes(96676583, 1)], [card_bytes(32061192, 0)]),
  )
  decoded = msg.decode_select_unselect_card(message)

  assert [card["code"] for card in decoded["unselect"]] == [32061192]


def test_encode_unselect_card_response():
  """第一个 int32 是「我选了 / 结束」，第二个才是下标——顺序错了就无限 RETRY。"""
  assert msg.encode_unselect_card_response(None) == struct.pack("<i", -1)
  assert msg.encode_unselect_card_response(3) == struct.pack("<ii", 1, 3)


def test_decode_card_event_reads_code_and_location():
  payload = struct.pack("<IBBII", 52698008, 0, 0x40, 5, 0x1)
  decoded = msg.decode_card_event(msg.Message(type=0, payload=payload))

  assert decoded["code"] == 52698008
  assert decoded["location"] == 0x40
  assert decoded["sequence"] == 5


def test_short_name_strips_archetype_prefix():
  assert short_name("码丽丝<兵卒>白兔") == "白兔"
  assert short_name("电子界小男巫") == "电子界小男巫"
  assert short_name("备份员@火灵天星") == "备份员@火灵天星"
  assert short_name("码丽丝<王后>红心加密") == "红心加密"
