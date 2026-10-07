---
name: flighty
description: Query Viktor's local Flighty cache for personal or friends' flights, status, delay forecasts, airports, airlines, statistics, and connections using the bundled CLI. Use for requests such as "my upcoming flights", "my Flighty stats", or "check my flight". NanoClaw has read-only access and does not fetch live schedules or write to Flighty.
---

# Flighty

Process steps in order. Do not skip ahead.

## Step 1 — Locate the CLI

Use Python 3.11+ with the bundled CLI and NanoClaw's read-only Flighty mount:

```bash
python3 /home/node/.claude/skills/tessl__flighty/scripts/flighty.py \
  --db /workspace/extra/flighty/MainFlightyDatabase.db doctor
```

Pass this `--db` option before every subcommand. The mount is available only in
the main Telegram swarm. If it is missing, report that Flighty access is not
configured for this chat; do not guess another user's database path. No API key
or MCP server is required. The Mac Flighty app must sync its cache for results
to reflect new changes. The mount contains a consistent SQLite snapshot exported
by the host every minute, not the live app database. Read
`/workspace/extra/flighty/snapshot.json` before time-sensitive answers:
`checked_at` records the last successful source check, `snapshot_created_at`
records the last changed export, and `source_modified_at` describes the local
app cache. If `checked_at` is older than five minutes, report the exporter as
stale and qualify the answer. A recent check does not prove Flighty fetched
fresh airline data.

## Step 2 — Select the operation

Read [references/commands.md](references/commands.md) for arguments and examples. Invoke the CLI rather than generating SQL or reimplementing calculations. Translate the request into explicit filters and dates; clarify missing details only when they affect the result. Global options precede the subcommand. Default scope is the owner; select friends or all only when requested. Use `doctor` when database access or owner inference needs diagnosis, and `--user-id` when inference is ambiguous or the user specifies an account.

For "next flight", use `list --upcoming --limit 1`; for historical statistics use `stats --year YYYY`. Use full flight codes, and specify `--date` or `--id` to disambiguate repeated services. An omitted date selects the most recent scheduled matching instance, which may be a future flight. Paginate when the request requires more than one page. Choose airport IATA codes when known.

## Step 3 — Execute the CLI

Success writes one JSON envelope `{ok:true, command, data}` to stdout and exits 0. Failures exit 1 and write `{ok:false,error}` to stderr. Help and version are plain text. Empty results are valid; do not invent flights or missing values. Handle errors using the stated diagnostic without editing Flighty's schema or bypassing filesystem access restrictions.

This NanoClaw integration is read-only. Do not invoke `--write`, change mount
permissions, or edit the database. An explicitly requested `add` preview may
use full flight code, airports, and departure/arrival datetimes with UTC
offsets supplied by the user; do not guess missing details. A preview is not a
saved flight. Actual additions must be made in Flighty or through the separately
authorized host skill.

## Step 4 — Explain the result

Summarize the relevant returned fields. Dates are UTC unless otherwise stated; use returned airport timezone identifiers to present local times and label the zone. Status and delay forecasts reflect Flighty's local cache, not a fresh network lookup. Missing values mean unavailable data. A below-minimum connection is a calculated flag, not a guarantee about making the flight. Label an add preview as a preview; this integration never saves it.
