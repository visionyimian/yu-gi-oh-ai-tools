#!/usr/bin/env python3
"""Append missing cards to a deck-analyzer resource table.

The two CSVs under ``resources/`` are the analyzer's baseline: for every card in the
table, ``deck-analyzer`` judges how badly that card hurts the deck being analyzed.
Card data (desc / atk / def / level / race / attribute / type) comes from the card
database via ``ygo-db-cli``; the ``frequency`` column is hand-curated meta prevalence
and is therefore supplied on the command line.

Both tables share one layout::

    name,desc,frequency,atk,def,level,race,attribute,type

Cards that already exist are skipped, so the command is safe to re-run. The target file
is rewritten as UTF-8 without BOM, CRLF line endings and no trailing newline, and empty
rows (the stray ",," line both tables used to end with) are dropped.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
from pathlib import Path

HEADER = ["name", "desc", "frequency", "atk", "def", "level", "race", "attribute", "type"]
DEFAULT_FREQUENCY = "uncommon"
DEFAULT_CSV = Path(__file__).resolve().parent.parent / "resources" / "handtraps.csv"


def cell(value: object) -> str:
  """Render a card field as a CSV cell; a missing field becomes an empty string."""
  return "" if value is None else str(value)


def to_crlf(text: str) -> str:
  return text.replace("\r\n", "\n").replace("\n", "\r\n")


def parse_add(spec: str) -> tuple[str, str]:
  """Parse ``NAME=FREQUENCY``; a bare NAME falls back to uncommon."""
  name, _, frequency = spec.partition("=")
  return name.strip(), frequency.strip() or DEFAULT_FREQUENCY


def collect_cards(payload: object) -> list[dict]:
  """Normalise the accepted JSON shapes into a list of card dicts.

  Accepts a list of cards, a ``{"exact": ..., "maybe": [...]}`` reply as printed by
  ``ygo-db-cli get-cards-by-name``, or a single card object.
  """
  if isinstance(payload, list):
    return [item for item in payload if isinstance(item, dict) and item.get("name")]

  if isinstance(payload, dict):
    cards: list[dict] = []
    if isinstance(payload.get("exact"), dict):
      cards.append(payload["exact"])
    cards.extend(item for item in payload.get("maybe") or [] if isinstance(item, dict))
    if not cards and payload.get("name"):
      cards.append(payload)
    return [item for item in cards if item.get("name")]

  return []


def load_lookup(path: Path) -> dict[str, dict]:
  cards = collect_cards(json.loads(path.read_text(encoding="utf-8-sig")))
  return {card["name"]: card for card in cards}


def fetch_from_cli(db_names: list[str], cli: str, lang: str) -> tuple[dict[str, dict], dict]:
  found: dict[str, dict] = {}
  missing: dict[str, list[str]] = {}

  for name in db_names:
    try:
      completed = subprocess.run(
        [cli, "get-cards-by-name", name, "--lang", lang, "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
      )
    except FileNotFoundError:
      raise SystemExit(
        f"cannot run {cli!r}: install ygo-db-cli and put it on PATH, "
        f"or point at it explicitly with --cli"
      ) from None
    if completed.returncode != 0:
      raise SystemExit(f"ygo-db-cli failed for {name!r}: {completed.stderr.strip()}")

    payload = json.loads(completed.stdout) if completed.stdout.strip() else {}
    cards = collect_cards(payload)
    exact = next((card for card in cards if card["name"] == name), None)
    if exact is None:
      missing[name] = [card["name"] for card in cards][:5]
    else:
      found[name] = exact

  return found, missing


def resolve_from_lookup(names: list[str], path: Path) -> tuple[dict[str, dict], dict]:
  by_name = load_lookup(path)
  found: dict[str, dict] = {}
  missing: dict[str, list[str]] = {}

  for name in names:
    card = by_name.get(name)
    if card is None:
      missing[name] = [known for known in by_name if name in known][:5]
    else:
      found[name] = card

  return found, missing


def read_rows(path: Path) -> tuple[list[str], list[list[str]], int]:
  """Return (header, data rows, number of empty rows dropped)."""
  with path.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.reader(handle))

  if not rows:
    raise SystemExit(f"{path} is empty")

  header = rows[0]
  if header != HEADER:
    raise SystemExit(f"unexpected header in {path}: {header}")

  dropped = sum(1 for row in rows[1:] if not row or not row[0].strip())
  body = [row for row in rows[1:] if row and row[0].strip()]
  return header, body, dropped


def write_rows(path: Path, header: list[str], body: list[list[str]]) -> int:
  """Write the table back in the checked-out style and return the byte size."""
  buffer = io.StringIO()
  csv.writer(buffer, lineterminator="\r\n").writerows([header, *body])

  data = buffer.getvalue()
  if data.endswith("\r\n"):
    data = data[: -len("\r\n")]

  path.write_bytes(data.encode("utf-8"))
  return len(data)


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(
    description="Append missing cards to a deck-analyzer resource table.",
  )
  parser.add_argument(
    "--csv",
    type=Path,
    default=DEFAULT_CSV,
    help="target table (default: %(default)s)",
  )
  parser.add_argument(
    "--add",
    action="append",
    required=True,
    metavar="NAME[=FREQUENCY]",
    help="card to append; repeatable, frequency defaults to uncommon",
  )
  parser.add_argument(
    "--lookup",
    type=Path,
    help="JSON card dump; when omitted ygo-db-cli is queried instead",
  )
  parser.add_argument(
    "--cli",
    default="ygo-db-cli",
    help="ygo-db-cli executable (default: %(default)s)",
  )
  parser.add_argument(
    "--lang",
    default="zh-CN",
    help="card language passed to the CLI (default: %(default)s)",
  )
  parser.add_argument(
    "--dry-run",
    action="store_true",
    help="report what would change without writing the file",
  )
  args = parser.parse_args(argv)

  specs = [parse_add(spec) for spec in args.add]
  header, body, dropped = read_rows(args.csv)
  existing = {row[0] for row in body}

  for name, _ in specs:
    if name in existing:
      print(f"skip   {name} (already present)")

  pending = [(name, frequency) for name, frequency in specs if name not in existing]
  if not pending and not dropped:
    print("nothing to do")
    return 0

  added: list[list[str]] = []
  if pending:
    names = [name for name, _ in pending]
    if args.lookup is not None:
      found, missing = resolve_from_lookup(names, args.lookup)
    else:
      found, missing = fetch_from_cli(names, args.cli, args.lang)

    if missing:
      detail = "\n".join(
        f"  {name}  candidates: {', '.join(candidates) or '(none)'}"
        for name, candidates in missing.items()
      )
      raise SystemExit(f"card not found in the card database:\n{detail}")

    for name, frequency in pending:
      card = found[name]
      added.append(
        [
          card["name"],
          to_crlf(cell(card.get("desc"))),
          frequency,
          cell(card.get("atk")),
          cell(card.get("def")),
          cell(card.get("level")),
          cell(card.get("race")),
          cell(card.get("attribute")),
          cell(card.get("type")),
        ]
      )
      print(f"add    {card['name']} [{frequency}] {cell(card.get('type'))}")

  if args.dry_run:
    print(f"\ndry run: {len(added)} card(s) would be added, {dropped} empty row(s) dropped")
    return 0

  write_rows(args.csv, header, [*body, *added])
  print(
    f"\nrows: {len(body) + dropped} -> {len(body) + len(added)}"
    f"  (dropped {dropped} empty)"
    f"  file: {args.csv}"
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
