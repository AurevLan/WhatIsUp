#!/bin/sh
set -e

echo "[WhatIsUp] Running database migrations..."
alembic upgrade head

echo "[WhatIsUp] Running first-boot initialisation..."
python -m whatisup.init_data

echo "[WhatIsUp] Starting server..."
exec "$@"
