#!/bin/sh
set -e

echo "[WhatIsUp] Running database migrations..."
alembic upgrade head

echo "[WhatIsUp] Starting server..."
exec "$@"
