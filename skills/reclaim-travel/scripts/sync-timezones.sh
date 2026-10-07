#!/usr/bin/env bash
# Authorized TripIt -> Reclaim timezone mirror. Google calendar writes stay off.
set -euo pipefail
: "${HTTPS_PROXY:?OneCLI HTTPS_PROXY is required}"
python3 - <<'PY'
import json
from pathlib import Path
config = json.loads(Path('/workspace/group/travel-automation.json').read_text())
if config.get('mode') != 'timezones-only':
    raise SystemExit('Timezone sync is not enabled for this chat.')
PY
if [ ! -s /workspace/group/tripit-url.txt ]; then
    echo 'TripIt feed is missing for this chat.' >&2
    exit 1
fi
export TRIPIT_ICAL_URL="$(cat /workspace/group/tripit-url.txt)"
export RECLAIM_API_TOKEN=onecli-managed
export ENABLE_OOO=0
unset GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET GOOGLE_REFRESH_TOKEN
unset TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID SNS_TOPIC_ARN
cd /usr/local/lib/node_modules/reclaim-tripit-timezones-sync
node sync.mjs sync --output=json
