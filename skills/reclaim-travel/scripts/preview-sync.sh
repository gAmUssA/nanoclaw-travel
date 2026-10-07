#!/usr/bin/env bash
# Read-only preview; no Telegram/SNS notification credentials are forwarded.
set -euo pipefail
: "${HTTPS_PROXY:?OneCLI HTTPS_PROXY is required}"
if [ ! -s /workspace/group/tripit-url.txt ]; then
    echo 'TripIt feed is missing for this chat.' >&2
    exit 1
fi
export TRIPIT_ICAL_URL="$(cat /workspace/group/tripit-url.txt)"
export RECLAIM_API_TOKEN=onecli-managed
export ENABLE_OOO=0
unset TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID SNS_TOPIC_ARN
cd /usr/local/lib/node_modules/reclaim-tripit-timezones-sync
node sync.mjs dry-run --output=json
