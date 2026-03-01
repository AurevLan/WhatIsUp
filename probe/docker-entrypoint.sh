#!/bin/sh
set -e

# If PROBE_API_KEY is not set but the shared file exists, read it from there.
if [ -z "$PROBE_API_KEY" ] && [ -f "/shared/PROBE_API_KEY" ]; then
    PROBE_API_KEY=$(cat /shared/PROBE_API_KEY)
    export PROBE_API_KEY
fi

exec "$@"
