#!/usr/bin/env bash
# Build the WhatIsUp Android APK inside the mobile build container.
#
# Usage:
#   mobile/build.sh init      # first-time: install npm deps + add android platform
#   mobile/build.sh sync      # rebuild web bundle and sync to android/
#   mobile/build.sh apk       # produce a debug APK at frontend/android/app/build/outputs/apk/debug/
#   mobile/build.sh shell     # interactive shell inside the build image
#
# All commands run inside the whatisup-mobile image with frontend/ mounted at /workspace.
set -euo pipefail

cd "$(dirname "$0")/.."
IMAGE=whatisup-mobile

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    docker build -t "$IMAGE" mobile/
fi

TTY_FLAGS=""
if [ -t 0 ] && [ -t 1 ]; then TTY_FLAGS="-it"; fi

run() {
    docker run --rm $TTY_FLAGS \
        -v "$PWD/frontend:/workspace" \
        -w /workspace \
        "$IMAGE" \
        bash -c "$1"
}

case "${1:-}" in
    init)
        run "npm install && npx cap add android && npm run build && npx cap sync android"
        ;;
    sync)
        run "npm run build && npx cap sync android"
        ;;
    apk)
        run "npm run build && npx cap sync android && cd android && ./gradlew assembleDebug"
        echo
        echo "APK ready: frontend/android/app/build/outputs/apk/debug/app-debug.apk"
        echo "Install with: adb install -r frontend/android/app/build/outputs/apk/debug/app-debug.apk"
        ;;
    shell)
        run "bash"
        ;;
    *)
        echo "usage: $0 {init|sync|apk|shell}" >&2
        exit 2
        ;;
esac
