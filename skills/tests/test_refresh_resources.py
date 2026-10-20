"""Tests for the deck-analyzer resource refresh script."""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "deck-analyzer" / "scripts"))
from refresh_resources import main

HEADER_LINE = "name,desc,frequency,atk,def,level,race,attribute,type"
ASH_ROW = (
  '灰流丽,"这个卡名的效果1回合只能使用1次。\r\n'
  '①：把这张卡从手卡丢弃才能发动。",common,0,1800,3,不死,炎,怪兽卡|效果|调整'
)
BUG = {
  "name": "幽鬼兔",
  "desc": "这个卡名的效果1回合只能使用1次。\n①：把手卡·场上的这张卡送去墓地才能发动。",
  "atk": 0,
  "def": 1800,
  "level": 3,
  "race": "念动力",
  "attribute": "光",
  "type": "怪兽卡|效果|调整",
  "count": 1,
}


def write_table(path: Path, rows: list[str]) -> None:
  """Write a table using the same byte style as the checked-out files."""
  path.write_bytes("\r\n".join([HEADER_LINE, *rows]).encode("utf-8"))


def read_table(path: Path) -> list[list[str]]:
  with path.open(encoding="utf-8", newline="") as handle:
    return list(csv.reader(handle))


def write_lookup(path: Path, payload: object) -> None:
  path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_appends_card_from_lookup(tmp_path):
  """A card missing from the table is appended with the database fields."""
  table = tmp_path / "handtraps.csv"
  write_table(table, [ASH_ROW])
  lookup = tmp_path / "lookup.json"
  write_lookup(lookup, [BUG])

  assert main(["--csv", str(table), "--lookup", str(lookup), "--add", "幽鬼兔=uncommon"]) == 0

  rows = read_table(table)
  assert [row[0] for row in rows[1:]] == ["灰流丽", "幽鬼兔"]
  assert rows[2][2] == "uncommon"
  assert rows[2][3:6] == ["0", "1800", "3"]
  assert rows[2][8] == "怪兽卡|效果|调整"


def test_skips_card_already_present(tmp_path, capsys):
  """Re-running with an existing card must not duplicate it."""
  table = tmp_path / "handtraps.csv"
  write_table(table, [ASH_ROW])
  lookup = tmp_path / "lookup.json"
  write_lookup(lookup, [])

  assert main(["--csv", str(table), "--lookup", str(lookup), "--add", "灰流丽"]) == 0

  assert [row[0] for row in read_table(table)[1:]] == ["灰流丽"]
  assert "skip" in capsys.readouterr().out


def test_frequency_defaults_to_uncommon(tmp_path):
  """Omitting '=FREQUENCY' falls back to uncommon."""
  table = tmp_path / "handtraps.csv"
  write_table(table, [])
  lookup = tmp_path / "lookup.json"
  write_lookup(lookup, [BUG])

  main(["--csv", str(table), "--lookup", str(lookup), "--add", "幽鬼兔"])

  assert read_table(table)[1][2] == "uncommon"


def test_drops_empty_rows(tmp_path):
  """The stray ',,' line is removed instead of being appended to."""
  table = tmp_path / "handtraps.csv"
  write_table(table, [ASH_ROW, ",,"])
  lookup = tmp_path / "lookup.json"
  write_lookup(lookup, [BUG])

  main(["--csv", str(table), "--lookup", str(lookup), "--add", "幽鬼兔"])

  assert [row[0] for row in read_table(table)[1:]] == ["灰流丽", "幽鬼兔"]


def test_writes_crlf_without_bom_or_trailing_newline(tmp_path):
  """The output keeps the byte style of the checked-out files."""
  table = tmp_path / "handtraps.csv"
  write_table(table, [ASH_ROW])
  lookup = tmp_path / "lookup.json"
  write_lookup(lookup, [BUG])

  main(["--csv", str(table), "--lookup", str(lookup), "--add", "幽鬼兔"])

  data = table.read_bytes()
  assert not data.startswith(b"\xef\xbb\xbf")
  assert not data.endswith(b"\n")
  text = data.decode("utf-8")
  assert text.count("\n") == text.count("\r\n")


def test_dry_run_leaves_the_file_untouched(tmp_path):
  """--dry-run reports the change without writing."""
  table = tmp_path / "handtraps.csv"
  write_table(table, [ASH_ROW])
  lookup = tmp_path / "lookup.json"
  write_lookup(lookup, [BUG])
  before = table.read_bytes()

  assert main(["--csv", str(table), "--lookup", str(lookup), "--add", "幽鬼兔", "--dry-run"]) == 0

  assert table.read_bytes() == before


def test_unknown_card_reports_candidates(tmp_path):
  """An unresolved name exits with the candidate list instead of writing."""
  table = tmp_path / "handtraps.csv"
  write_table(table, [ASH_ROW])
  lookup = tmp_path / "lookup.json"
  write_lookup(lookup, [BUG])

  with pytest.raises(SystemExit) as exc_info:
    main(["--csv", str(table), "--lookup", str(lookup), "--add", "不存在的卡"])

  assert "not found" in str(exc_info.value)


def test_lookup_accepts_cli_reply_shape(tmp_path):
  """The raw `get-cards-by-name` reply (exact/maybe) is accepted as lookup input."""
  table = tmp_path / "handtraps.csv"
  write_table(table, [])
  lookup = tmp_path / "lookup.json"
  write_lookup(lookup, {"exact": BUG, "maybe": [], "total": 1})

  main(["--csv", str(table), "--lookup", str(lookup), "--add", "幽鬼兔"])

  assert read_table(table)[1][0] == "幽鬼兔"


def test_missing_cli_reports_actionable_error(tmp_path):
  """A CLI that cannot be executed must not leak a subprocess traceback."""
  table = tmp_path / "handtraps.csv"
  write_table(table, [])

  with pytest.raises(SystemExit) as exc_info:
    main(["--csv", str(table), "--cli", "definitely-not-a-real-cli", "--add", "幽鬼兔"])

  assert "--cli" in str(exc_info.value)
