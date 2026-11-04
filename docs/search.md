# Search

`/search/` is `skins/search.py`. It must stay **index-backed** and
**time-limited** ([ADR 0002](adr/0002-index-backed-search.md)): before
2026-11-03 every search read the whole skins table, and a burst of them stalled
the site ([incident](incidents/2026-11-03-search-stall.md)).

## Modes

| `mode` | Matches | Index |
|---|---|---|
| `relevance` (default) | Full-text on labels, description, name, creator, plus fuzzy name (trigram) | `skin_search_vector_gin`, `skin_name_trgm` |
| `name` / `creator` / `description` | Case-insensitive "contains" | `skin_name_trgm` / `skin_creator_trgm` / `skin_description_trgm` |
| `tags` | Labels | none yet (known weak spot; part of the search rework) |

Empty query: a random sample of one page, picked by primary key (no table scan),
for any `sort`.

## How relevance works

1. **Prefilter with indexes:** `search_vector @@ query OR name % query`, with
   `pg_trgm.similarity_threshold = 0.2`. Postgres answers this from the two GIN
   indexes, leaving a few hundred rows at most.
2. **Score only those rows:** keep rank ≥ 0.1 (`MIN_RANK`) or name similarity
   > 0.2 (`MIN_NAME_SIMILARITY`), order by rank. These rules are unchanged from
   the original search; the prefilter only skips rows that could never pass.

`search_vector` is a stored generated column (Postgres keeps it up to date on
every insert/update): labels and description weight A, name B, creator C, text
config `english` (`SKIN_SEARCH_CONFIG`). Queries must use the same config or
they miss the index.

"Contains" modes use the custom `ilike_contains` lookup (`core/lookups.py`),
which emits `ILIKE` with `%`/`_` escaped, so the trigram indexes on the plain
columns are used.

## Time limit

Each search runs inside `time_limited_queries(SEARCH_STATEMENT_TIMEOUT_MS)`
(`core/db.py`, default 3000 ms): Postgres cancels a slower query, the view logs
`search timed out` and shows "That search took too long. Try a more specific
search term." instead of holding a worker.

## Changing search safely

- `tests/test_search.py::TestIndexes` runs each mode with sequential scans
  disabled and asserts the plan names the expected index. If you change a
  query and this fails, the new query can't use an index.
- New filters (e.g. labels/tags) need their own index (GIN on `labels`).
- To try a change against realistic data, run `scripts/load_test_search.py`
  against a **local** server (it refuses production hosts).
