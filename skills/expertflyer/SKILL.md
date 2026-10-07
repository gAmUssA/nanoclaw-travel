---
name: expertflyer
description: Check seat availability or fare-class (upgrade) inventory on a flight, judge whether the seat already assigned is beaten by anything open, review seats across every upcoming flight at once, or create an ExpertFlyer alert when the wanted thing is not already available. Actions - check fare-class/upgrade inventory (Z class, upgrade certificate, SkyTeam partner); check seats on one flight; judge one held seat against everything open in its cabin and the cabins above it; review upcoming flights for better seats; create a seat or fare-class alert; diagnose access. Use when the operator asks whether a seat is open, asks about Comfort+ / premium economy / business availability, asks whether their seat is the best available or worth changing, says make sure I have the best seats or check my upcoming flights for better seats, asks to be alerted when a seat or fare class opens up, or a new booking has just appeared.
---

# ExpertFlyer

## Viktor's preferences and party context

Solo: prefer an **aisle** within the ticketed cabin. Window/middle remain
alternatives, not absolute exclusions. No exit-row, forward-row or recline
preference was stated. The client ranks aisles first and does not call a row
change an upgrade by itself. `preferred_total` counts available aisles.

Family: prefer **3+1**, with three adjacent seats in one block and the fourth
seat directly across the aisle in the same row. Use the family command below,
not the solo `assess` verdict. It includes middle seats and validates explicit
seat-map aisle geometry; it never guesses adjacency from letters. Preserve the
family group before any individual seat preference. Check party context in
`/workspace/group/travel-preferences.json` and trusted memory; if unknown,
ask once when a recommendation depends on it. Never infer family/solo from a
destination or assume one ticket proves solo travel.

```bash
python3 /home/node/.claude/skills/tessl__expertflyer/scripts/expertflyer.py family-seats \
    --airline UA --flight 486 --date 2026-10-08 --cabin economy \
    --origin EWR --destination MCO
```

Optionally pass `--held 12A,12B,12C,12D` only for seats confirmed held by the
family. Occupied seats not explicitly held by them stay unavailable. Exit
rows are excluded unless all four passengers are known eligible; only then
may `--allow-exit` be used. `count: 0` means no verified 3+1 group is currently
available in that map, not that the cabin is full. Single-seat alerts do not
watch this four-seat arrangement. Do not create one as a substitute.

This skill is an action router — pick the step that matches the operator's intent and execute only that step. Do not run other steps; do not parallelize.

Every alert request is **check first, alert only if absent**. An alert for something already bookable is worse than useless: it delays the booking while the operator waits for an email describing space they could have taken on the spot. Report the check result either way, so it is visible why no alert was set. Only skip the check when the operator explicitly says to set the alert regardless.

The browser automation, the ExpertFlyer credential and the session live in the `jbaruch/expertflyer-api` service. This container holds none of them — every step below is one HTTP call through `skills/expertflyer/scripts/expertflyer.py`, which reads `EXPERTFLYER_API_URL` and `EXPERTFLYER_API_TOKEN`.

## Step 1 — Check fare-class (upgrade) inventory

For "is there Z on KL642", "can I use an upgrade certificate", "check business availability".

```bash
python3 /home/node/.claude/skills/tessl__expertflyer/scripts/expertflyer.py fare-class \
    --origin JFK --destination AMS --date 2026-08-31 \
    --airline KL --flight 642 --class Z
```

Outputs `flight`, `seats`, `available`, `display_capped`, `alternatives` (other flights that day with space), `recommend_alert`.

`seats: 0` means the bucket exists and is empty — an answer, not a missing value. `display_capped: true` means *at least* that many. Codeshares are excluded by default because inventory lives on the operating carrier; pass `--include-codeshares` to see them.

Report the count plainly. When `available` is true, say so and **do not** offer an alert. When false, name any `alternatives` and offer the alert (Step 5).

Finish here unless the operator accepts the alert.

## Step 2 — Check seat availability

For "is there a non-middle seat in Comfort+ on DL2957", "any window left in premium economy".

```bash
python3 /home/node/.claude/skills/tessl__expertflyer/scripts/expertflyer.py seats \
    --airline DL --flight 2957 --date 2026-08-11 \
    --cabin "comfort+" --want aisle
```

`--cabin` takes the cabin the operator named — `premium economy`, `comfort+`, `business`, `first`, `economy` — or a bare code. Premium economy is Delta's **Premium Select** (`A`) and is a different cabin from Comfort+ (`W`); the service rejects an unrecognised cabin rather than falling back to economy. `--want` accepts `non-middle` (aisle and window), `aisle,window`, `middle`, or `any`. `--origin`/`--destination` are optional — omit them and the route is resolved from the flight number.

Outputs `cabin_present`, `seats_in_cabin`, `available_total`, `recommend_alert`, the service's own criteria filter `matching`, and three fields the client adds by ranking the response:

- `ranked` — bookable seats worth taking, best first, each with a `why` such as `12A (window)`
- `best` — the top seat's description, or `null` when nothing is worth taking
- `acceptable_total` — how many seats are worth taking

Use `preferred_total` to distinguish preferred aisles from alternatives, never `matching` alone. Ranking reflects the confirmed solo aisle preference. `matching` is the service filter; `preferred_total` counts aisles, while `ranked` also retains non-aisle alternatives. If no aisle exists, label alternatives clearly instead of calling them preferred.

A response carrying `error` has no `best`, `ranked` or `acceptable_total`. Absent is not `null`. Go to Step 6.

On every other response:

1. `cabin_present` is false — the aircraft has no such cabin. Say so. Offer no alert.
2. `preferred_total` is positive — name the best aisle and say it is open. Offer no alert.
3. `preferred_total` is zero — no aisle is currently available. Report other positions as alternatives and offer an aisle alert only for a solo traveller. Create an alert only if Viktor requests it.

Ranking rules live in `skills/expertflyer/scripts/seat_quality.py`.

Finish here unless the operator accepts the alert.

## Step 3 — Judge one held seat

For "is 21F the best I can do on DL2957".

Step 2 answers what is open. It does not answer whether any of it beats the seat already assigned, and those are different questions. This one runs the comparison in the script, so no seat is judged by eye.

```bash
python3 /home/node/.claude/skills/tessl__expertflyer/scripts/expertflyer.py assess \
    --airline DL --flight 2957 --date 2026-08-11 \
    --held 21F --held-position window
```

`--held` is the seat currently assigned. `--held-cabin` is optional; omit it and the cabin is resolved from the aircraft's row extents. `--held-position` is `window`, `aisle` or `middle`; omit it and the column is read off the open seats in the same cabin. `--scan-up` sets how many cabins above the held one to include — the default and its cost are in `skills/expertflyer/scripts/expertflyer.py`.

Get the held seat from the matching Flighty record via `tessl__flighty` before
calling this. The CLI returns `seatNumber`; it may be absent or cached. If the
seat is missing or Viktor says it changed, ask him for the current seat. Do not
write it back to the read-only Flighty mount or call byAir. Never infer the seat
from a previous conversation. Pass `--held-position` only when known; otherwise
let the seat map resolve it.

Do not ask for the cabin initially. Omit `--held-cabin` and the cabin is resolved from the aircraft. `held_cabin_from` reports `stated` or `resolved`.

Pass `--held-cabin` only when the operator names a cabin themselves, or when a response asks for it.

Responses carrying `error` and `detail` instead of a `verdict`:

1. `bad_request` — an unusable argument, such as an unrecognised cabin or a seat that is not a designator. `cabins_absent` rides along when the aircraft has no such cabin.
2. `unrankable` — a seat the ranking refused. Step 6 covers it.
3. any service fault, with `cabin_failed` and `cabins_requested` naming the cabin that did not load. Go to Step 6.

`verdict: "no_held_seat"` carries `verdict` and `detail` alone. `held_cabin_unresolved` adds `reason` and `cabins_absent`, plus `row_in_cabins` on every reason but `rows_unavailable`. Neither carries `held`.

Every other response carries `verdict`, `held`, `cabins_scanned`, `cabins_absent`, `cabins_unscanned`, `seats_compared`, `held_cabin_from` and `held_cabin_corroborated`. `held` carries `why` on every shape except `held_position_unknown`, which has no position to describe.

`optimal` and `upgrade` add `upgrades`, `best_upgrade`, `cabin_openings`, `alert_recommended` and `alert_cabins`. Every other verdict adds `detail` and carries none of those five. Their absence is the contract, not a malformed response.

`upgrades` holds seats in the held cabin. The operator selects those in the airline's app.

`cabin_openings` holds seats in a better cabin. Those are not a seat change — taking one is a fare change or an upgrade clearance. Never tell the operator to go select one. Step 1 answers whether the upgrade inventory exists.

`alert_cabins` is the authoritative list of cabins to watch. Offer the alert on those and no others, never on every cabin in `cabins_scanned`. An empty list with `alert_recommended: false` means there is nothing to watch for. Selection lives in `skills/expertflyer/scripts/expertflyer.py` — the `ALERT_RUNGS` constant and the alert block in `_assess`.

`cabins_scanned` is the whole evidence base, `seats_compared` is its size, and `acceptable_by_cabin` breaks it down per cabin into seats worth taking. `cabins_unscanned` lists the cabins above the sweep that were never read; widen it with `--scan-up` to see further, which does not widen `alert_cabins`.

`held_cabin_corroborated` is `true` when the held seat's row is in the cabin it was assessed as, `false` when it is not, and `null` when the service could not settle it. `held_cabin_from` says where the cabin came from: `stated` from `--held-cabin`, `resolved` from the aircraft's row extents. `held_cabin_source` says which evidence checked it: `rows` is the cabin's own extent and decides it either way, `seats` is the older availability-derived fallback and can only ever confirm. Derivation is in `skills/expertflyer/scripts/expertflyer.py`.

On `null`, `row_seen_in` names the scanned cabins where the row did turn up. A non-empty list is a reason to confirm the cabin with the operator before acting on the verdict. Report the assessment either way.

Report `verdict` as it comes. Do not re-derive it from `upgrades`:

**`optimal`** — nothing the operator can select beats the held seat.

- Say so, naming the cabins in `cabins_scanned`.
- Name `held.why`.
- Name `cabins_unscanned` as not checked, when it is non-empty.
- Report `cabin_openings` when it is non-empty.
- Offer the alert (Step 5) on `alert_cabins`.

Never report `optimal` as "nothing better exists". The sweep reads `cabins_scanned` and stops. A cabin in `cabins_unscanned` may hold a better seat and was never looked at.

Never say the held seat beat a cabin. `optimal` compares it against the seats that were open, never against a cabin's standing. `acceptable_by_cabin` gives the reason per cabin: `0` is a cabin with nothing worth taking.

**`upgrade`** — an open seat in the held cabin beats it.

- Name `best_upgrade`. The operator selects it in the airline's app.
- Report `cabin_openings` when it is non-empty.
- Offer no alert.

**`no_held_seat`** — no seat was passed.

- Get the seat from the matching Flighty record, or from the operator.
- Report nothing about seat quality.

**`held_cabin_unresolved`** — the layout does not say which cabin holds that row. `reason` says why.

- Relay `detail`.
- `shared_row` — ask the operator which cabin, naming those in `row_in_cabins`.
- `no_such_row` — check the seat and the flight with the operator.
- `rows_unavailable` — ask the operator for the cabin.
- Re-run with `--held-cabin`.
- Report nothing about seat quality.

**`held_position_unknown`** — the seat map does not say what the column is.

- Ask the operator whether the seat is a window, an aisle or a middle.
- Pass the answer as `--held-position`.

**`nothing_open`** — no open seat was found in any scanned cabin, so nothing was compared.

- Say no seat is open to move to, better or worse.
- Never report this as the held seat being best.
- Offer to widen the sweep with `--scan-up`.
- Check the cabin: a sold-out cabin and a seat that is not in that cabin look identical here.

**`held_cabin_mismatch`** — the held seat's row is outside the extent of the cabin it was assessed as.

- Relay `detail`. It names the cabin's row range, and the cabin the row belongs to when the sweep saw it.
- Re-run with the corrected `--held-cabin`.
- Report no verdict from this run. The cabin sets the ladder rung and the exit-row layout.

**`error`** — go to Step 6.

- `cabin_failed` names the cabin that did not load.

`no_held_seat`, `held_position_unknown`, `nothing_open`, `held_cabin_mismatch` and `held_cabin_unresolved` exit non-zero. None is an answer about the seat. Report no verdict on any of them.

Ranking rules live in `skills/expertflyer/scripts/seat_quality.py`.

Finish here unless the operator accepts the alert.

## Step 4 — Review seats on upcoming flights

For "make sure I have the best seats", or after a new booking appears.

```bash
python3 /home/node/.claude/skills/tessl__expertflyer/scripts/upcoming-flights.py \
    --now "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

Outputs `{"flights": [...], "count": N, "trips": [...], "excluded": [...], "excluded_count": N}`. Each flight carries `airline`, `flight`, `origin`, `destination`, `date`, `departs_utc`, `summary` and `uid`, soonest first.

The pass covers the next trip. `--trips N` widens it to the next N; `--trips 0` covers every upcoming flight. The default, the lead window and the trip-edge slack are named constants in `skills/expertflyer/scripts/upcoming-flights.py`.

`excluded` holds the upcoming flights the trip bound left out. Say how many when the operator asked about their seats generally rather than about one trip. `trips` names what was covered.

`count: 0` with a non-empty `excluded` means no upcoming trip covers those flights. Report that rather than reporting nothing.

Collect the held seat for every flight before assessing any of them. Read each
from the matching Flighty record. Ask the operator once, in a single message,
for every flight with a missing or outdated seat. Do not write to Flighty.
Ask for no cabins initially — Step 3 resolves them.

Then run Step 3 once per flight, adding `--date-fallback`. Read `date_fallback_applied` to see which date answered. Do not pass it in Step 3 for a date the operator named.

Report only the flights that need something:

- `upgrade` → name the flight and `best_upgrade`
- `cabin_openings` non-empty → name the cabin and the seat
- say a `cabin_openings` seat needs a fare change or an upgrade
- never report a `cabin_openings` seat as a seat selection
- `optimal` → one line that the seat holds up across `cabins_scanned`, or nothing when the operator asked only for problems
- `no_held_seat`, `held_position_unknown`, `nothing_open`, `held_cabin_mismatch` or `held_cabin_unresolved` → name the flight as unanswered, never as fine
- `cabins_absent` covering the held cabin → report it; a seat cannot be in a cabin the aircraft lacks

A flight whose verdict never came back is not a flight with good seats. Say which ones were not answered.

Then offer the alert once, for every flight whose `alert_recommended` is true, naming those flights and their `alert_cabins`. Step 3's alert offer is not optional here.

Finish here unless the operator accepts an alert.

## Step 5 — Create an alert

Only after Step 1, 2, 3 or 4 reported the wanted thing absent, or the operator explicitly asked for the alert regardless.

```bash
# Seat alert — needs --cabin and --want
python3 /home/node/.claude/skills/tessl__expertflyer/scripts/expertflyer.py create-alert \
    --kind seat --airline DL --flight 2957 --date 2026-08-11 \
    --origin ATL --destination YYZ --cabin "comfort+" --want aisle

# Fare-class alert — needs --class
python3 /home/node/.claude/skills/tessl__expertflyer/scripts/expertflyer.py create-alert \
    --kind fare-class --airline KL --flight 642 --date 2026-08-31 \
    --origin JFK --destination AMS --class Z
```

Route is required here. Steps 1 to 4 all report it. Outputs `{"created": true, "alert_id": ..., "status": "ACTIVE", "verified_in_account": true}`.

The service refuses to duplicate an active alert of the same kind on the same flight and class, returning `{"created": false, "reason": "already_exists", "alert_id": ...}`. A seat alert and a fare-class alert on one flight are different watches, so having one never blocks the other. Relay the refusal; do not retry with `--force` unless the operator asks.

`verified_in_account` comes from the service re-reading the account after submitting. Report a failure there as **not created**, never as success.

Finish here.

## Step 6 — Diagnose access

Run when a step above reports an `error` field.

`unrankable` is **not** an access fault. On it:

- Relay `detail`. It names the seat the ranking refused.
- Offer no alert.
- Do not run the command below.
- Finish here.

On every other value:

```bash
python3 /home/node/.claude/skills/tessl__expertflyer/scripts/expertflyer.py alerts
```

The `error` value names the fault and is not re-derivable here — relay it verbatim:

- `unreachable` — the service is down or `EXPERTFLYER_API_URL` is wrong. Nothing to retry until it is up.
- `tls` — the service answered but its certificate could not be verified. The endpoint is fine; the trust store is not. The detail names the fix.
- `auth` — the service could not authenticate; its `detail` carries ExpertFlyer's own message. It re-tries a login itself before reporting, so this means the credentials in the service need attention.
- `blocked` — ExpertFlyer's bot wall rejected the request. Never retry it in a loop.

Finish here.
