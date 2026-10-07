# CLI commands

Run the bundled `scripts/flighty.py` with Python 3.11+ or use the installed `flighty` entry point. Below, `flighty` means either form.

Global options, placed before the subcommand:

- `--db PATH`: overrides `FLIGHTY_DB_PATH`, then the standard macOS Flighty database location.
- `--user-id ID`: overrides `FLIGHTY_USER_ID`; choose an active user shown by `doctor`.
- `--now ISO`: fixes the clock for reproducible filtering, archive inference, and creation timestamps. Naive timestamps and date-only filters use UTC.

| Command | Inputs and behavior |
| --- | --- |
| `doctor` | Database path, available tables, user IDs. Does not require inferred owner. |
| `list`, `search` | `--scope own\|friends\|all`, `--upcoming` or `--past`, `--include-archived`, `--airline`, `--departure-airport`, `--arrival-airport`, `--after`, `--before`, `--friend`, `--limit`, `--offset`. |
| `friends` | Same filters with friends scope. |
| `get`, `status`, `forecast` | Exactly one of `--flight UA194` or `--id ID`; optional `--date YYYY-MM-DD` in departure airport local time, `--scope`. Latest scheduled matching instance if date omitted. Includes archived records. |
| `airports QUERY`, `airlines QUERY` | Accent-insensitive substring search; `--limit`, `--offset`. |
| `stats` | `--year YYYY`, plus list filters except pagination. Counts all matching flights, including future and cancelled; use `--past` for flown history. Distinct country count across both endpoints. |
| `connections` | Owner's recorded connections, `--limit`, `--offset`. Scheduled layover minutes and minimum-time flag. |
| `add` | Required `--flight`, `--departure-airport`, `--arrival-airport`, `--departure`, `--arrival`. Optional `--seat`, `--cabin`, `--booking-reference`. Preview unless `--write --backup PATH`. |

Examples:

```bash
flighty list --upcoming --limit 1
flighty friends --friend Felix --upcoming
flighty get --flight UA194 --date 2026-10-06
flighty search --departure-airport EWR --after 2026-01-01 --before 2026-12-31T23:59:59Z
flighty stats --year 2025 --past
flighty airports Zurich
flighty --now 2026-10-06T12:00:00Z list --upcoming
flighty add --flight UA194 --departure-airport SFO --arrival-airport MUC \
  --departure 2026-10-06T14:00:00-07:00 --arrival 2026-10-07T10:00:00+02:00
```

Read operations open SQLite in read-only mode and use a transaction for a consistent snapshot. Flights sort by scheduled departure, ID, and user ID; catalog results sort by relevance and ID. Explicit inputs, a fixed database snapshot, and `--now` yield repeatable JSON. Filters use inclusive UTC boundaries; a date-only `--before` ends at the start of that day. Archive handling retains upstream's heuristic for older databases that auto-archive past flights.

Owner inference uses relationship frequency, then active flight count. This remains a heuristic; use `--user-id` for certainty. Ties fail rather than choosing an arbitrary user. Optional Flight and Ticket fields tolerate schema additions/removals; required relations must retain the upstream layout. Weather fields are passed through using their installed schema names.

Opaque binary Flight fields used internally by the app are omitted from JSON results.

Creation never calls AirLabs and requires explicit instants. A preview validates airport/airline references and known insertion columns. A write takes an immediate transaction, makes a consistent SQLite backup at a new path, and inserts Flight, UserFlight, and optional Ticket atomically. IDs derive deterministically from user, code, route, and departure. Existing owner flights with that tuple return `already_exists` without a write; retries do not update ticket data. Preview cannot guarantee that every constraint in an unknown app schema will accept the insert. An insert failure rolls back and retains the backup.

This writes Flighty's undocumented local storage. A backup is required for writes; app acceptance and cloud synchronization need verification in Flighty. No real database should be modified as part of testing this plugin.
