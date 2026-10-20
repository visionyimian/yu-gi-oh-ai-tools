"""Tests for the ocg-banlist skill."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "ocg-banlist" / "scripts"))
from fetch_banlist import main, parse_lists, pick_list, read_ydk


FIXTURES = Path(__file__).parent / "fixtures" / "banlist"
LFLIST = FIXTURES / "lflist_sample.conf"


def write_deck(path: Path, main_ids: list[int]) -> None:
  lines = ["#main", *(str(card_id) for card_id in main_ids), "#extra", "!side"]
  path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


def test_parse_lists():
  """Lists are split on '!', limits parsed, leading zeros normalised."""
  lists = parse_lists(LFLIST.read_text(encoding="utf-8"))

  assert [name for name, _ in lists] == ["2026.10", "2026.9 TCG"]
  ocg = lists[0][1]
  assert ocg[95454996] == (0, "Maliss <Q> White Binder")
  assert ocg[69272449] == (1, "Maliss <P> White Rabbit")
  assert ocg[8903700] == (1, "Djinn Releaser of Rituals")  # 08903700
  assert ocg[14558127] == (2, "Ash Blossom & Joyous Spring")


def test_pick_default_is_ocg():
  """Without --tcg the newest non-TCG list is selected."""
  name, cards = pick_list(parse_lists(LFLIST.read_text(encoding="utf-8")), None, False)

  assert name == "2026.10"
  assert 95454996 in cards


def test_pick_tcg():
  """--tcg selects the TCG list."""
  name, cards = pick_list(parse_lists(LFLIST.read_text(encoding="utf-8")), None, True)

  assert name == "2026.9 TCG"
  assert 30342076 in cards
  assert 95454996 not in cards


def test_pick_by_name():
  name, _ = pick_list(parse_lists(LFLIST.read_text(encoding="utf-8")), "2026.9 tcg", False)

  assert name == "2026.9 TCG"


def test_pick_unknown_list_exits():
  with pytest.raises(SystemExit) as exc_info:
    pick_list(parse_lists(LFLIST.read_text(encoding="utf-8")), "1999.1", False)

  assert "没有列表" in str(exc_info.value)


def test_read_ydk_counts(tmp_path):
  """Duplicate lines are counted; non-card lines are ignored."""
  deck = tmp_path / "deck.ydk"
  body = "#main\r\n69272449\r\n69272449\r\n#extra\r\n95454996\r\n!side\r\n"
  deck.write_text(body, encoding="utf-8")

  counts = read_ydk(deck)

  assert counts[69272449] == 2
  assert counts[95454996] == 1


def test_summary_output(tmp_path, capsys):
  """The default text output reports the list name and the buckets."""
  assert main(["--file", str(LFLIST)]) == 0

  out = capsys.readouterr().out
  assert "2026.10" in out
  assert "禁止 1" in out


def test_json_output(tmp_path):
  output = tmp_path / "ocg_limit.json"

  assert main(["--file", str(LFLIST), "--format", "json", "-o", str(output)]) == 0

  payload = json.loads(output.read_text(encoding="utf-8"))
  assert payload["list"] == "2026.10"
  assert payload["format"] == "ocg"
  assert {"passcode": 69272449, "limit": 1, "name": "Maliss <P> White Rabbit"} in payload["cards"]


def test_check_legal_deck(tmp_path, capsys):
  deck = tmp_path / "legal.ydk"
  write_deck(deck, [69272449, 14558127, 14558127])  # limited 1 + semi 2

  assert main(["--file", str(LFLIST), "--check", str(deck)]) == 0
  assert "通过" in capsys.readouterr().out


def test_check_illegal_deck(tmp_path, capsys):
  deck = tmp_path / "illegal.ydk"
  write_deck(deck, [69272449, 69272449, 95454996])  # limited 1 twice + forbidden

  assert main(["--file", str(LFLIST), "--check", str(deck)]) == 1

  out = capsys.readouterr().out
  assert "违规 2 处" in out
  assert "禁止" in out
  assert "限制 1" in out
