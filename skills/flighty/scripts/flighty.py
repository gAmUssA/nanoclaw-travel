#!/usr/bin/env python3
"""Local Flighty CLI: JSON stdout, JSON errors stderr, no network dependencies."""
import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = '0.1.1'
DEFAULT_DB = '~/Library/Containers/com.flightyapp.flighty/Data/Documents/MainFlightyDatabase.db'


class FlightyError(Exception):
    pass


def instant(value):
    """Date-only and naive ISO values are UTC, never host-local time."""
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return int(parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp())


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFD', str(value or ''))
                   if unicodedata.category(c) != 'Mn').casefold()


def code(value):
    normalized = re.sub(r'[ -]', '', value.upper())
    match = re.fullmatch(r'([A-Z]{2}|[0-9][A-Z]|[A-Z][0-9])([0-9]+)', normalized)
    if not match:
        raise FlightyError('Use a full airline flight code, such as UA194.')
    return match.groups()


def positive(value):
    number = int(value)
    if number < 1 or number > 10000:
        raise argparse.ArgumentTypeError('must be between 1 and 10000')
    return number


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError('must be nonnegative')
    return number


class Database:
    def __init__(self, path, user_id, now, write=False):
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise FlightyError(f'Database not found: {self.path}. Open Flighty or set --db.')
        self.conn = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if write else '?mode=ro'),
                                    uri=True, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        if not write:
            self.conn.execute('PRAGMA query_only=ON')
        self.conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        self.now = now
        self.user_id = user_id
        self.schema = {r[0]: {c[1] for c in self.conn.execute(f'PRAGMA table_info("{r[0]}")')}
                       for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                       if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', r[0])}

    def close(self):
        self.conn.close()

    def rows(self, table):
        if table not in self.schema:
            raise FlightyError(f'Unsupported Flighty schema: missing table {table}.')
        return [dict(row) for row in self.conn.execute(f'SELECT * FROM "{table}"')
                if 'deleted' not in row.keys() or row['deleted'] is None]

    def owner(self):
        users = {row['userId'] for row in self.rows('UserFlight')}
        if self.user_id:
            if self.user_id not in users:
                raise FlightyError('Selected user has no active UserFlight rows.')
            return self.user_id
        counts = Counter()
        if 'ConnectedFriendRelationship' in self.schema:
            for row in self.rows('ConnectedFriendRelationship'):
                counts.update([row['senderUserId'], row['receiverUserId']])
        counts = Counter({key: val for key, val in counts.items() if key in users})
        if not counts:
            counts.update(row['userId'] for row in self.rows('UserFlight'))
        if not counts:
            raise FlightyError('Cannot infer owner: provide --user-id for an existing user.')
        ranked = counts.most_common()
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            raise FlightyError('Owner is ambiguous; select --user-id (see doctor).')
        return ranked[0][0]

    def flights(self, scope='own'):
        owner = self.owner()
        airports = {r['id']: r for r in self.rows('Airport')}
        airlines = {r['id']: r for r in self.rows('Airline')}
        profiles = {r['userId']: r for r in self.rows('Profile')} if 'Profile' in self.schema else {}
        tickets = {(r['userId'], r['flightId']): r for r in self.rows('Ticket')} if 'Ticket' in self.schema else {}
        flights = {r['id']: r for r in self.rows('Flight')}
        results = []
        for membership in self.rows('UserFlight'):
            uid = membership['userId']
            if scope == 'own' and uid != owner or scope == 'friends' and uid == owner:
                continue
            f = flights.get(membership['flightId'])
            if f is None:
                continue
            dep = airports.get(f.get('departureAirportId'), {})
            arr = airports.get(f.get('scheduledArrivalAirportId'), {})
            airline = airlines.get(f.get('airlineId'), {})
            result = dict(f)
            result.update(user_id=uid, is_archived=membership.get('isArchived', 0),
                          flight_code=str(airline.get('iata') or '') + str(f.get('number') or ''),
                          airline_name=airline.get('name'), airline_iata=airline.get('iata'),
                          friend_name=profiles.get(uid, {}).get('fullName') or profiles.get(uid, {}).get('firstName'))
            for prefix, airport in [('departure', dep), ('arrival', arr)]:
                for out, key in [('airport_iata', 'iata'), ('city', 'city'), ('country', 'country'),
                                 ('timezone', 'timeZoneIdentifier'), ('airport_name', 'name')]:
                    result[f'{prefix}_{out}'] = airport.get(key)
            ticket = tickets.get((uid, f['id']), {})
            for key in ['seatNumber', 'cabinClass', 'pnr']:
                result[key] = ticket.get(key)
            results.append(result)
        return sorted(results, key=lambda r: (r.get('departureScheduleGateOriginal') or 0, r['id'], r['user_id']))

    def filtered(self, args, paginate=True):
        rows = self.flights(getattr(args, 'scope', 'own'))
        past = [r for r in rows if (r.get('departureScheduleGateOriginal') or 0) < self.now]
        automatic = bool(past) and sum(bool(r['is_archived']) for r in past) / len(past) >= .9
        if not getattr(args, 'include_archived', False) and not automatic:
            rows = [r for r in rows if not r['is_archived']]
        after = instant(args.after) if getattr(args, 'after', None) else None
        before = instant(args.before) if getattr(args, 'before', None) else None
        if after is not None and before is not None and after > before:
            raise FlightyError('--after must be no later than --before.')
        for name, keys in [('airline', ['airline_iata', 'airline_name']),
                           ('departure_airport', ['departure_airport_iata', 'departure_city']),
                           ('arrival_airport', ['arrival_airport_iata', 'arrival_city']),
                           ('friend', ['friend_name'])]:
            wanted = getattr(args, name, None)
            if wanted:
                rows = [r for r in rows if any(fold(wanted) in fold(r.get(k)) for k in keys)]
        selected = []
        for row in rows:
            ts = row.get('departureScheduleGateOriginal')
            if (getattr(args, 'upcoming', False) and (ts is None or ts < self.now)
                    or getattr(args, 'past', False) and (ts is None or ts >= self.now)
                    or after is not None and (ts is None or ts < after)
                    or before is not None and (ts is None or ts > before)):
                continue
            selected.append(row)
        if paginate:
            return selected[args.offset:args.offset + args.limit]
        return selected

    def get(self, args):
        rows = self.flights(args.scope)
        if args.id:
            rows = [r for r in rows if r['id'] == args.id]
        else:
            airline, number = code(args.flight)
            rows = [r for r in rows if r['flight_code'].upper() == airline + number]
        if args.date:
            day = datetime.strptime(args.date, '%Y-%m-%d').date()
            rows = [r for r in rows if r.get('departureScheduleGateOriginal') is not None and
                    datetime.fromtimestamp(r['departureScheduleGateOriginal'],
                                           ZoneInfo(r.get('departure_timezone') or 'UTC')).date() == day]
        if not rows:
            raise FlightyError('Flight not found in selected scope/date.')
        return rows[-1]

    def insert(self, table, values):
        missing = set(values) - self.schema.get(table, set())
        if missing:
            raise FlightyError(f'Unsupported write schema for {table}: missing {sorted(missing)}.')
        names = ','.join(f'"{name}"' for name in values)
        self.conn.execute(f'INSERT INTO "{table}" ({names}) VALUES ({",".join("?" for _ in values)})',
                          list(values.values()))


def render_flight(row):
    # Flighty carries opaque serialized app state alongside queryable columns.
    result = {key: value for key, value in row.items() if not isinstance(value, bytes)}
    for key, value in result.items():
        if ('Schedule' in key or key in ['created', 'lastUpdated', 'lastKnownDepartureDate',
                                        'lastKnownArrivalDate', 'equipmentFirstFlightDate']) and isinstance(value, (int, float)):
            result[key] = iso(value)
    return result


def status(row):
    result = render_flight(row)
    for prefix in ['departure', 'arrival']:
        original = row.get(prefix + 'ScheduleGateOriginal')
        estimated = row.get(prefix + 'ScheduleGateActual') or row.get(prefix + 'ScheduleGateEstimated')
        result[prefix + '_delay_minutes'] = (estimated - original) // 60 if estimated is not None and original is not None else None
    result['status'] = ('cancelled' if row.get('isCancelled') else 'landed' if row.get('arrivalScheduleGateActual')
                        else 'in_air' if row.get('departureScheduleGateActual')
                        else 'delayed' if (result['departure_delay_minutes'] or 0) > 15 else 'scheduled')
    return result


def forecast(row):
    observations = row.get('delayForecastObservations') or 0
    result = {'flight_code': row['flight_code'], 'observations': observations,
              'mean_delay_minutes': row.get('delayForecastDelayMean')}
    for key, suffix in [('early', 'Early'), ('ontime', 'Ontime'), ('late_15', 'Late15'),
                        ('late_30', 'Late30'), ('late_45', 'Late45'), ('cancelled', 'Canceled'), ('diverted', 'Diverted')]:
        count = row.get('delayForecast' + suffix + 'Count')
        result[key + '_pct'] = round(100 * count / observations, 1) if observations and count is not None else None
    return result


def stats(rows, year):
    if year:
        start, end = instant(f'{year:04d}-01-01'), instant(f'{year + 1:04d}-01-01')
        rows = [r for r in rows if start <= (r.get('departureScheduleGateOriginal') or 0) < end]
    distance = sum(r.get('distance') or 0 for r in rows)
    countries = {r.get(k) for r in rows for k in ['departure_country', 'arrival_country']} - {None, ''}
    airlines = Counter(r.get('airline_iata') for r in rows)
    routes = Counter(f"{r.get('departure_airport_iata')} -> {r.get('arrival_airport_iata')}" for r in rows)
    top = lambda counts: [{'name': key, 'flight_count': val} for key, val in sorted(counts.items(), key=lambda p: (-p[1], p[0] or ''))[:5]]
    return {'total_flights': len(rows), 'total_distance_km': distance, 'total_distance_miles': round(distance * .621371),
            'unique_countries': len(countries), 'unique_airlines': len(set(airlines) - {None}),
            'unique_airports': len({r.get(k) for r in rows for k in ['departure_airport_iata', 'arrival_airport_iata']} - {None}),
            'cancelled_flights': sum(bool(r.get('isCancelled')) for r in rows),
            'top_airlines': top(airlines), 'top_routes': top(routes), 'year': year}


def add(db, args):
    airline_code, number = code(args.flight)
    def lookup(table, wanted):
        matches = [r for r in db.rows(table) if str(r.get('iata') or '').upper() == wanted.upper()]
        if len(matches) != 1:
            raise FlightyError(f'{table} IATA code must match exactly one active row: {wanted}.')
        return matches[0]
    airline = lookup('Airline', airline_code)
    dep, arr = lookup('Airport', args.departure_airport), lookup('Airport', args.arrival_airport)
    departure, arrival = instant(args.departure), instant(args.arrival)
    if not re.search(r'T\d\d:\d\d.*(?:Z|[+-]\d\d:\d\d)$', args.departure) or not re.search(r'T\d\d:\d\d.*(?:Z|[+-]\d\d:\d\d)$', args.arrival):
        raise FlightyError('Creation requires full ISO datetimes with explicit offsets or Z.')
    if arrival <= departure:
        raise FlightyError('Arrival must be after departure.')
    owner = db.owner()
    key = f'{owner}:{airline_code}{number}:{dep["id"]}:{arr["id"]}:{departure}'
    flight_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'flighty-cli:' + key))
    existing = [r for r in db.flights('own') if r['flight_code'].upper() == airline_code + number
                and r.get('departureAirportId') == dep['id'] and r.get('scheduledArrivalAirportId') == arr['id']
                and r.get('departureScheduleGateOriginal') == departure]
    if existing:
        return {'action': 'already_exists', 'flight_id': existing[0]['id'], 'written': False}
    result = {'action': 'create', 'flight_id': flight_id, 'flight_code': airline_code + number,
              'departure_airport': dep['iata'], 'arrival_airport': arr['iata'],
              'departure': iso(departure), 'arrival': iso(arrival), 'written': False}
    flight = dict(id=flight_id, number=number, departureAirportId=dep['id'], scheduledArrivalAirportId=arr['id'],
                  actualArrivalAirportId=arr['id'], airlineId=airline['id'], isCancelled=0, hasOfficialData='0',
                  distance=0, lastKnownDepartureDate=departure, lastKnownArrivalDate=arrival,
                  departureScheduleGateOriginal=departure, arrivalScheduleGateOriginal=arrival,
                  created=db.now, lastUpdated=db.now)
    membership = dict(userId=owner, flightId=flight_id, isRandom=0, isProUpgrade=0, isMyFlight=1,
                      isArchived=0, importSource='CLI', lastUpdated=db.now, created=db.now)
    ticket = dict(userId=owner, flightId=flight_id, seatNumber=args.seat, seatPosition=None,
                  cabinClass=args.cabin, pnr=args.booking_reference, lastUpdated=db.now)
    inserts = [('Flight', flight), ('UserFlight', membership)]
    if args.seat or args.cabin or args.booking_reference:
        inserts.append(('Ticket', ticket))
    for table, values in inserts:
        if set(values) - db.schema.get(table, set()):
            raise FlightyError(f'Unsupported write schema: {table}. No rows written.')
    if args.write:
        if not args.backup:
            raise FlightyError('--write requires --backup PATH for a SQLite snapshot.')
        backup = Path(args.backup).expanduser().resolve()
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup_fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(backup_fd)
        try:
            # A second read connection backs up the committed state before our transaction.
            with closing(sqlite3.connect(db.path.as_uri() + '?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(str(backup))) as destination:
                    source.backup(destination)
            for table, values in inserts:
                db.insert(table, values)
            db.conn.commit()
        except Exception:
            db.conn.rollback()
            raise
        result.update(written=True, backup=str(backup))
    return result


def execute(db, args):
    command = args.command
    if command == 'doctor':
        return {'database': str(db.path), 'tables': sorted(db.schema),
                'users': sorted({r['userId'] for r in db.rows('UserFlight')}),
                'owner_inference': 'relationship frequency, then flight count; ties require --user-id',
                'source': 'local cache; refresh in Flighty for newer data'}
    if command in ['airports', 'airlines']:
        rows = db.rows('Airport' if command == 'airports' else 'Airline')
        keys = ['iata', 'icao', 'name', 'city' if command == 'airports' else 'alliance']
        rows = [r for r in rows if any(fold(args.query) in fold(r.get(k)) for k in keys)]
        return sorted(rows, key=lambda r: (-(r.get('relevance') or 0), r['id']))[args.offset:args.offset + args.limit]
    if command in ['list', 'friends', 'search']:
        return [render_flight(r) for r in db.filtered(args)]
    if command in ['get', 'status', 'forecast']:
        row = db.get(args)
        return {'get': render_flight, 'status': status, 'forecast': forecast}[command](row)
    if command == 'stats':
        return stats(db.filtered(args, paginate=False), args.year)
    if command == 'connections':
        flights = {r['id']: r for r in db.flights('own')}
        airports = {r['id']: r for r in db.rows('Airport')}
        results = []
        for connection in db.rows('Connection'):
            inbound = flights.get(connection['arrivingFlightId'])
            outbound = flights.get(connection['departingFlightId'])
            if not inbound or not outbound:
                continue
            arr, dep = inbound.get('arrivalScheduleGateOriginal'), outbound.get('departureScheduleGateOriginal')
            minutes = (dep - arr) // 60 if arr is not None and dep is not None else None
            minimum = connection.get('mctMinutes')
            results.append({'id': connection['id'], 'inbound_flight': inbound['flight_code'],
                            'onward_flight': outbound['flight_code'],
                            'connection_airport': airports.get(connection['waitingAirportId'], {}).get('iata'),
                            'arrival': iso(arr), 'departure': iso(dep), 'layover_minutes': minutes,
                            'minimum_connection_minutes': minimum,
                            'below_minimum': minutes < minimum if minutes is not None and minimum is not None else None})
        return sorted(results, key=lambda r: (r['arrival'] or '', r['id']))[args.offset:args.offset + args.limit]
    if command == 'add':
        return add(db, args)
    raise FlightyError('Unknown command.')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise FlightyError(message + ' (see --help)')


def parser():
    root = Parser(description=__doc__)
    root.add_argument('--version', action='version', version=VERSION)
    root.add_argument('--db', default=os.environ.get('FLIGHTY_DB_PATH', DEFAULT_DB))
    root.add_argument('--user-id', default=os.environ.get('FLIGHTY_USER_ID'))
    root.add_argument('--now', help='ISO datetime; pins time for reproducible queries')
    commands = root.add_subparsers(dest='command', required=True)
    for name in ['doctor', 'list', 'friends', 'search', 'get', 'status', 'forecast', 'airports', 'airlines', 'stats', 'connections', 'add']:
        p = commands.add_parser(name)
        if name in ['list', 'friends', 'search', 'airports', 'airlines', 'connections']:
            p.add_argument('--limit', type=positive, default=50)
            p.add_argument('--offset', type=nonnegative, default=0)
        if name in ['list', 'friends', 'search', 'stats']:
            p.add_argument('--include-archived', action='store_true')
            timing = p.add_mutually_exclusive_group()
            timing.add_argument('--upcoming', action='store_true')
            timing.add_argument('--past', action='store_true')
            for option in ['airline', 'departure-airport', 'arrival-airport', 'after', 'before', 'friend']:
                p.add_argument('--' + option)
            if name == 'friends':
                p.set_defaults(scope='friends')
            else:
                p.add_argument('--scope', choices=['own', 'friends', 'all'], default='own')
        if name in ['get', 'status', 'forecast']:
            target = p.add_mutually_exclusive_group(required=True)
            target.add_argument('--id')
            target.add_argument('--flight')
            p.add_argument('--date', help='departure date in departure airport local time')
            p.add_argument('--scope', choices=['own', 'friends', 'all'], default='own')
        if name in ['airports', 'airlines']:
            p.add_argument('query')
        if name == 'stats':
            p.add_argument('--year', type=int)
        if name == 'add':
            p.add_argument('--flight', required=True)
            for option in ['departure-airport', 'arrival-airport', 'departure', 'arrival']:
                p.add_argument('--' + option, required=True)
            for option in ['seat', 'cabin', 'booking-reference', 'backup']:
                p.add_argument('--' + option)
            p.add_argument('--write', action='store_true')
    return root


def main(argv=None):
    db = None
    try:
        args = parser().parse_args(argv)
        now = instant(args.now) if args.now else int(datetime.now(timezone.utc).timestamp())
        if getattr(args, 'year', None) is not None and not 1 <= args.year <= 9998:
            raise FlightyError('--year must be between 1 and 9998.')
        db = Database(args.db, args.user_id, now, getattr(args, 'write', False))
        result = execute(db, args)
        print(json.dumps({'ok': True, 'command': args.command, 'data': result}, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except (FlightyError, sqlite3.Error, OSError, ValueError, KeyError, OverflowError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if db:
            db.close()


if __name__ == '__main__':
    sys.exit(main())
