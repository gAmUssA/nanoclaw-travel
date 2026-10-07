#!/usr/bin/env python3
"""Wake for unsent pre-departure briefings; never send or mutate providers."""

import argparse
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from zoneinfo import ZoneInfo

GROUP = Path(os.environ.get("NANOCLAW_GROUP_DIR", "/workspace/group"))
SKILLS = Path("/home/node/.claude/skills")
FLIGHTY = Path(os.environ.get("FLIGHTY_SNAPSHOT_DIR", "/workspace/extra/flighty"))


def instant(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def atomic_json(path, value):
    fd, tmp = tempfile.mkstemp(prefix=".pretrip-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def flight_zone(flight):
    return (
        ZoneInfo(flight["timezone"])
        if flight.get("timezone")
        else instant(flight["departure"]).tzinfo
    )


def flight_identity(flight):
    # Stable across a delay/re-time on the same departure-local date.
    start = instant(flight["departure"])
    tz = flight_zone(flight)
    return "|".join(
        [
            flight["code"],
            flight["origin"],
            flight["destination"],
            start.astimezone(tz).date().isoformat(),
        ]
    )


def due_at(flight, mode):
    departure = instant(flight["departure"])
    zone = flight_zone(flight)
    local = departure.astimezone(zone)
    if mode == "24-hours":
        return departure - timedelta(hours=24)
    if mode == "departure-morning":
        return min(
            datetime.combine(local.date(), time(7), zone),
            departure - timedelta(hours=2),
        )
    return datetime.combine(local.date() - timedelta(days=1), time(9), zone)


def due_journeys(flights, sent, now, mode):
    ordered = sorted(flights, key=lambda f: instant(f["departure"]))
    journeys = []
    for flight in ordered:
        if not journeys:
            journeys.append([flight])
            continue
        previous = journeys[-1][-1]
        arrival = instant(previous.get("arrival"))
        gap = instant(flight["departure"]) - arrival if arrival else None
        # Only join a known route continuity with a plausible connection.
        if (
            gap is not None
            and timedelta(0) <= gap <= timedelta(hours=12)
            and previous["destination"] == flight["origin"]
        ):
            journeys[-1].append(flight)
        else:
            journeys.append([flight])
    due = []
    for journey in journeys:
        first = journey[0]
        departure = instant(first["departure"])
        keys = [
            hashlib.sha256(flight_identity(f).encode()).hexdigest()[:24]
            for f in journey
        ]
        if any(key in sent for key in keys) or not (
            due_at(first, mode) <= now < departure
        ):
            continue
        due.append(
            {
                "key": keys[0],
                "keys": keys,
                "due_at": due_at(first, mode).isoformat(),
                "flights": journey,
            }
        )
    return due


def refresh_itinerary(now):
    schedule = GROUP / "travel-schedule.json"
    if schedule.exists() and now.timestamp() - schedule.stat().st_mtime < 6 * 3600:
        return []
    errors = []
    for skill, script in [
        ("nightly-travel-sync", "refresh-travel-schedule.py"),
        ("check-travel-bookings", "build-travel-db.py"),
    ]:
        path = SKILLS / f"tessl__{skill}/scripts/{script}"
        try:
            result = subprocess.run(
                ["python3", str(path)], capture_output=True, text=True, timeout=130
            )
            if result.returncode:
                errors.append("TripIt itinerary cache refresh failed")
                break
        except (OSError, subprocess.SubprocessError):
            errors.append("TripIt itinerary cache refresh unavailable")
            break
    return errors


def collect_flights(now):
    flights = {}
    errors = []
    cancelled = []
    try:
        metadata = json.loads((FLIGHTY / "snapshot.json").read_text())
        checked = instant(metadata.get("checked_at"))
        if not checked or (now - checked).total_seconds() > 300:
            errors.append("Flighty exporter is stale; flight details are cached")
        result = subprocess.run(
            [
                "python3",
                str(SKILLS / "tessl__flighty/scripts/flighty.py"),
                "--db",
                str(FLIGHTY / "MainFlightyDatabase.db"),
                "list",
                "--after",
                (now - timedelta(days=1)).isoformat(),
                "--limit",
                "500",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        result_json = json.loads(result.stdout)
        if result.returncode or not result_json.get("ok"):
            raise ValueError("Flighty query failed")
        if len(result_json["data"]) == 500:
            errors.append(
                "Flighty list reached its limit; future flights may be truncated"
            )
        for f in result_json["data"]:
            dep = f.get("departureScheduleGateOriginal")
            arr = f.get("arrivalScheduleGateOriginal")
            if not instant(dep):
                continue
            flight = {
                "code": f.get("flight_code"),
                "origin": f.get("departure_airport_iata"),
                "destination": f.get("arrival_airport_iata"),
                "departure": dep,
                "arrival": arr,
                "timezone": f.get("departure_timezone"),
                "arrival_timezone": f.get("arrival_timezone"),
                "seat": f.get("seatNumber"),
                "cabin": f.get("cabinClass"),
                "flighty_id": f.get("id"),
                "source": "Flighty cache",
                "cached_at": f.get("lastUpdated"),
            }
            if not all(
                flight.get(k) for k in ("code", "origin", "destination", "timezone")
            ):
                continue
            if f.get("isCancelled"):
                cancelled.append(flight)
                continue
            flights[flight_identity(flight)] = flight
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        errors.append("Flighty data unavailable")
    try:
        events = json.loads((GROUP / "travel-schedule.json").read_text())
        for event in events:
            if event.get("type") != "Flight":
                continue
            match = re.search(
                r"\b([A-Z0-9]{2}\s*\d{1,4})\s+([A-Z]{3})\s+to\s+([A-Z]{3})\b",
                event.get("summary", ""),
            )
            dep = instant(event.get("start_local")) or instant(event.get("start"))
            if not match or not dep:
                continue
            flight = {
                "code": match[1].replace(" ", ""),
                "origin": match[2],
                "destination": match[3],
                "departure": dep.isoformat(),
                "arrival": event.get("end_local") or event.get("end"),
                "timezone": None,
                "source": "TripIt itinerary",
                "tripit_uid": event.get("uid"),
            }
            # Do not resurrect a Flighty-cancelled leg from a lagging TripIt feed.
            if any(
                f["code"] == flight["code"]
                and f["origin"] == flight["origin"]
                and f["destination"] == flight["destination"]
                and abs((instant(f["departure"]) - dep).total_seconds()) < 12 * 3600
                for f in cancelled
            ):
                continue
            # Match by UTC date/route when Flighty already supplies a named timezone.
            duplicate = next(
                (
                    f
                    for f in flights.values()
                    if f["code"] == flight["code"]
                    and f["origin"] == flight["origin"]
                    and f["destination"] == flight["destination"]
                    and abs((instant(f["departure"]) - dep).total_seconds()) < 12 * 3600
                ),
                None,
            )
            if duplicate:
                duplicate["tripit_departure"] = dep.isoformat()
                continue
            # The UTC timestamp alone cannot establish local briefing time.
            local = instant(event.get("start_local"))
            if not local:
                errors.append(f"No departure-local time for {flight['code']}")
                continue
            flight["local_offset_fallback"] = True
            flights[flight_identity(flight)] = flight
    except (OSError, ValueError, KeyError, TypeError):
        errors.append("TripIt itinerary cache unavailable")
    return list(flights.values()), list(dict.fromkeys(errors))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--mark-sent", nargs="+")
    parser.add_argument("--message-id")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    sent_path = GROUP / "pretrip-brief-sent.json"
    sent = json.loads(sent_path.read_text()) if sent_path.exists() else {}
    if args.mark_sent:
        if not args.message_id:
            raise ValueError("A confirmed Telegram message ID is required")
        for key in args.mark_sent:
            sent[key] = {"sent_at": now.isoformat(), "message_id": args.message_id}
        atomic_json(sent_path, sent)
        print(json.dumps({"marked": len(args.mark_sent)}))
        return
    config = json.loads((GROUP / "pretrip-brief-config.json").read_text())
    if not config.get("enabled"):
        print(json.dumps({"wake_agent": False, "data": {"reason": "disabled"}}))
        return
    errors = [] if args.preview else refresh_itinerary(now)
    flights, source_errors = collect_flights(now)
    errors += source_errors
    due = due_journeys(flights, sent, now, config["timing"])
    pending = {
        "created_at": now.isoformat(),
        "journeys": due,
        "source_warnings": list(dict.fromkeys(errors)),
        "timing": config["timing"],
    }
    if not args.preview:
        atomic_json(GROUP / "pretrip-brief-pending.json", pending)
    print(json.dumps({"wake_agent": bool(due), "data": pending}))


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            json.dumps(
                {
                    "wake_agent": True,
                    "data": {"error": "Pre-trip check failed: " + type(exc).__name__},
                }
            )
        )
