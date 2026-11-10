# ADR 0014: A counter on a row is changed in SQL under a lock, and can be recounted from its rows

**Status:** accepted, 2026-11-10 (RFC-0001 Phase 4, step 4.1)

**Context.** A skin's `upvotes` and `downvotes` are stored on the `Skin` row so
lists and leaderboards can sort by them without counting `SkinVote` rows on
every page. The old vote view read `skin.upvotes`, changed it in Python and
saved it back. Two votes at the same moment both read the same number, so one
was lost: in a test with separate database connections, 8 simultaneous votes
stored 2 or 3. Nothing could tell a drifted counter from a real one.

**Decision.**
- **The rows are the truth; the counter is a cache of them.** `SkinVote` rows
  decide; `Skin.upvotes`/`downvotes` must always equal their count.
- Every change to a counter goes through one service (`skins/votes.py:
  cast_vote`) that, in one short transaction, locks the parent row
  (`select_for_update`), changes the vote row, and moves the counters with
  `F()` expressions (never below zero, `Greatest(F(...) - 1, 0)`). The reply
  re-reads the counters after the write.
- A command recomputes every counter from its rows and reports drift
  (`manage.py audit_vote_counts`; `--fix` writes, each skin under its lock).
- Counts that are only read (favorites, friend counts on a page) are counted
  from rows in the query (`Skin.objects.with_favorite_count()`), not stored.
- Tests run concurrent votes on separate connections against real Postgres
  (`tests/test_votes.py`).

**Alternatives considered.**
- *Count rows on every read*: always right, but every list and leaderboard
  would count `SkinVote` rows per skin; sorting by score would need the count
  in every query.
- *Database triggers*: right under any writer, but invisible from the code and
  tests, and one more thing to migrate.
- *Optimistic locking (version column + retry)*: no lock waits, but a retry
  loop in the view for something that takes a millisecond.

**Consequences.**
- Votes on one skin are applied one after another; a vote waits at most for
  another vote's few-millisecond transaction.
- A new stored counter must follow the same rule: one service changes it under
  the parent row's lock with `F()`, and it gets an audit command. Otherwise,
  count it in the query.
- The production audit after 4.1 found no drift (2026-11-10). If counts ever
  look wrong: [runbook](../operations/runbook.md#vote-counts-look-wrong).
