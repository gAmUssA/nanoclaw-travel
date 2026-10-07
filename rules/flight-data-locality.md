---
alwaysApply: true
---

# Viktor's Travel Data Sources

## Flighty

- Viktor uses Flighty. Invoke `tessl__flighty` for his flights, cached status,
  delay forecasts, seats, connections, and flight statistics.
- The skill reads a host-exported Flighty SQLite snapshot through a read-only mount available
  in the main swarm. It makes no live flight-data request. State this freshness
  limit when presenting time-sensitive status; unavailable fields stay unknown.
- Use the bundled CLI rather than generating SQL. Default to Viktor's flights;
  query friends only when requested. Never write to the mounted database.
- Do not substitute byAir, buy an API subscription, or treat gateway placeholder
  credentials as an account connection. Viktor has not configured byAir.
- The bundled byAir `flight-assist` / `sync-tripit` polling pipeline and
  `drive-engine` remain disabled. Flighty lookup does not make those scripts
  Flighty-compatible or provide continuous live alerts.

## TripIt, Reclaim, and ExpertFlyer

- TripIt is the itinerary source for hotels, reservations, and trip plans when
  Viktor's connection is configured. Its private iCal feed can populate the
  upcoming travel schedule. Full history and confirmation-number lookups require
  a configured TripIt API service; do not invent results from a missing service.
- Flighty's own flight history and statistics are available independently;
  identify the source rather than claiming they represent all TripIt bookings.
- Reclaim calendar/timezone changes require Viktor's connected account and his
  selected automation scope. Onboarding alone does not enable calendar writes.
- ExpertFlyer provides seat and inventory lookups when its service is connected.
  Get the held seat from the matching Flighty record or Viktor. Viktor prefers aisle when solo and a verified 3+1 across-aisle group with
  family. Use the family-seats command for family trips; never split the group
  using solo ranking. No exit-row/front-row preference has been stated.
- Do not enable jobs whose provider connections have not passed a real access
  check. `onecli-managed` is a placeholder, not proof of authentication.

## Maps and Calendar

- Maps/traffic access is separate and is not configured by installing Flighty.
- Use Viktor's intended Google Calendar connection. Account ambiguity is a
  configuration error, never an empty calendar or permission to remove accounts.
