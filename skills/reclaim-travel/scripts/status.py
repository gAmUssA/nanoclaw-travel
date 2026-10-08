#!/usr/bin/env python3
"""Read Reclaim connection and travel settings through the agent's gateway."""

import json
import os
import ssl
import sys
import urllib.error
import urllib.request


def main():
    if not os.environ.get("HTTPS_PROXY"):
        print(json.dumps({"ok": False, "error": "OneCLI HTTPS_PROXY is required."}))
        return 1
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("NODE_EXTRA_CA_CERTS")
    context = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))

    def get(path):
        request = urllib.request.Request(
            "https://api.app.reclaim.ai" + path,
            headers={"Authorization": "Bearer onecli-managed", "Accept": "application/json"},
        )
        with opener.open(request, timeout=45) as response:
            return json.load(response)

    try:
        zones = get("/api/time-window-overrides")
        calendar = get("/api/calendars/primary")
    except urllib.error.HTTPError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": exc.code,
                    "error": (
                        "Reclaim rejected the read request. Check the main-agent grant and token."
                    ),
                }
            )
        )
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        print(json.dumps({"ok": False, "error": "Reclaim could not return valid data."}))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "defaultTimezone": zones.get("defaultTimezone"),
                "entries": zones.get("entries", []),
                "primaryCalendarConnected": bool(calendar.get("id")),
                "googleCalendarConnected": bool((calendar.get("data") or {}).get("id")),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
