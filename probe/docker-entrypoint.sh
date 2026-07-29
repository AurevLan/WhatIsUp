#!/bin/sh
set -e

# If PROBE_API_KEY is not set, read it from the secrets mount.
# `/probe-secrets` is the only volume the probe gets: it carries the API key and
# nothing else. The former `/shared` mount also exposed the first-boot superadmin
# password, which a compromised probe could read (audit F15). The legacy path is
# still tried for custom compose files that predate the split.
if [ -z "$PROBE_API_KEY" ]; then
    for _f in /probe-secrets/PROBE_API_KEY /shared/PROBE_API_KEY; do
        if [ -f "$_f" ]; then
            PROBE_API_KEY=$(cat "$_f")
            export PROBE_API_KEY
            break
        fi
    done
fi

exec "$@"
