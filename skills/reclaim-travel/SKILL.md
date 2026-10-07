---
name: reclaim-travel
description: Read Viktor's Reclaim travel timezone overrides and primary calendar, or preview TripIt travel timezone segments without changing Reclaim or Google Calendar. Use for Reclaim connection checks, current travel timezones, and previewing a TripIt-to-Reclaim sync.
---

# Reclaim travel

Choose the requested action. The account belongs to Viktor and is connected
through OneCLI in the main swarm. Credential placeholders alone never prove
access; require a successful authenticated response.

## Read current settings

```bash
python3 /home/node/.claude/skills/tessl__reclaim-travel/scripts/status.py
```

Returns the account's default timezone, travel overrides, and primary calendar
connection status. An empty override list is valid. A failed connection is not
an empty calendar. The script only sends GET requests and never prints tokens.

## Preview TripIt timezone sync

```bash
bash /home/node/.claude/skills/tessl__reclaim-travel/scripts/preview-sync.sh
```

The installed sync package reads the private TripIt feed and Reclaim's current
settings and returns JSON with `mode: dry-run`, `segments`, `homeTimezone`,
`conflicts`, and `errors`. Describe the proposed segments and any conflicts;
`noChanges` and empty `timezoneChanges` in dry-run do not mean that the current
Reclaim overrides already match. Never claim that the preview saved changes.

## Automatic timezone sync

Viktor authorized automatic travel-timezone sync on 2026-10-07. The host
LaunchAgent `com.nanoclaw.reclaim-timezones` runs it every hour and at login,
using `scripts/sync-reclaim-timezones.py` in the NanoClaw checkout. It mirrors
TripIt-derived timezone overrides into Reclaim. Google Calendar flight and OOO
blocks are disabled; enabling them needs a separate request from Viktor.

Read `/workspace/group/reclaim-sync-status.json` to check the last attempt,
last success, change count, and interval. A recent failure is not success just
because older data exists. After more than two hours without a successful run,
report the sync as stale. The authorized mode is recorded in
`/workspace/group/travel-automation.json`.

Do not schedule a second writer or run the upstream `nightly-travel-sync`
Reclaim step alongside this job. To force an immediate run or recover it, the
host command is `python3 scripts/sync-reclaim-timezones.py` from the NanoClaw
checkout; it owns the overlap lock and gateway setup. Previews and status reads
remain safe to run while the automatic job is enabled.
