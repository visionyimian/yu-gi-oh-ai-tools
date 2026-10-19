# deck-analyzer resources

Two curated tables that [`deck-analyzer`](../SKILL.md) uses as its analysis baseline.
They describe the **opponent's** toolkit, not the deck being analyzed.

| File | Question it answers | Consumed by |
|------|--------------------|-------------|
| `handtraps.csv` | 我展开时会被什么打断 | Step 5 手坑敏感度 → `handtrap_vulnerability` |
| `boardbreakers.csv` | 我建好的终场会被什么打穿 | Step 3 终场弱点 → `endboard_vulnerability` |

Both files share one layout:

```csv
name,desc,frequency,atk,def,level,race,attribute,type
```

- `desc`, `atk`, `def`, `level`, `race`, `attribute`, `type` come straight from the
  card database (`cards.cdb`). Spell and trap rows leave `atk`/`def`/`level`/`race`/
  `attribute` empty.
- `frequency` is **not** in the database: it is hand-curated meta prevalence
  (`common` / `uncommon`). Keep the vocabulary in sync with the `meta_prevalence`
  values used in `deck_analyzer.json` (`common` / `uncommon` / `rare`).

## Refreshing a table

Append cards with [`../scripts/refresh_resources.py`](../scripts/refresh_resources.py),
which pulls the card data from the CDB through `ygo-db-cli`:

```bash
# add to handtraps.csv (the default target)
python skills/deck-analyzer/scripts/refresh_resources.py \
  --add "增殖的G=common" --add "幽鬼兔"

# add to the other table
python skills/deck-analyzer/scripts/refresh_resources.py \
  --csv skills/deck-analyzer/resources/boardbreakers.csv \
  --add "闪电风暴=common"
```

`--cli` points at a specific binary when `ygo-db-cli` is not on `PATH`, `--lang`
switches the card language (`zh-CN` by default), and `--dry-run` reports the change
without touching the file.

Cards already present are skipped, so the command is safe to re-run. The file is
rewritten as UTF-8 without BOM, CRLF line endings and no trailing newline, and empty
rows (the stray `,,` line both tables used to end with) are dropped.

For an offline or reproducible run, feed it a JSON dump instead of querying the CLI:

```bash
ygo-db-cli get-cards-by-name 幽鬼兔 --format json > /tmp/lookup.json
python skills/deck-analyzer/scripts/refresh_resources.py \
  --lookup /tmp/lookup.json --add "幽鬼兔"
```

Both the raw `get-cards-by-name` reply (`{"exact": ..., "maybe": [...]}`) and a plain
JSON array of card objects are accepted.

## Tests

```bash
python -m pytest skills/tests/test_refresh_resources.py -q
```
