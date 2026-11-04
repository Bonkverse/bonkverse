# ADR 0002: Search must be index-backed and time-limited

**Status:** accepted, 2026-11-03 (#20)

**Context.** Every search read the whole skins table (240–770 ms each), which
combined with one worker stalled the site
([incident](../incidents/2026-11-03-search-stall.md)).

**Decision.**
- A stored generated `search_vector` column with a GIN index, and trigram GIN
  indexes on name, creator and description (migration 0024).
- Every search narrows rows with an index before scoring.
- Every search runs under a 3 s Postgres `statement_timeout`.
- A test runs each mode with sequential scans disabled and requires the
  expected index in the plan.

**Consequences.**
- Typical search is ~3 ms.
- Writes to skins update the generated column and indexes (negligible at our
  write rate).
- Any new search condition needs an index and a plan test.
- Ranking changes (weights, text config) require changing the generated column
  in a migration.
- Groundwork for the search rework: label filters need a GIN index on
  `labels`; semantic search (embeddings) would add a vector index alongside,
  not replace these.
