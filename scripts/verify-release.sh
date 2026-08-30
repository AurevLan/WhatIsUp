#!/usr/bin/env bash
#
# verify-release.sh — prove a WhatIsUp release actually came out of this
# repository's CI, before deploying it.
#
# Checks, for a given version:
#   - Cosign keyless signature on ghcr.io/aurevlan/whatisup-server
#   - Cosign keyless signature on ghcr.io/aurevlan/whatisup-probe
#   - Cosign keyless SBOM attestation (SPDX) on both images
#   - Cosign keyless signature on the release APK (sign-blob, Sigstore bundle)
#
# This script fails LOUDLY on any missing or invalid signature. It never
# exits 0 on an unsigned artifact — an "it passed" here has to mean
# something, or it is worse than not running it at all.
#
# Usage:
#   scripts/verify-release.sh <version>       # e.g. 1.25.0 or v1.25.0
#
# Requires: cosign (https://docs.sigstore.dev/cosign/installation/), curl.
#
# What a green run here proves, and what it does NOT prove — see
# SECURITY.md § "Vérifier une release".

set -euo pipefail

REPO_OWNER="aurevlan"
REPO_SLUG="AurevLan/WhatIsUp"
ISSUER="https://token.actions.githubusercontent.com"
RELEASE_IDENTITY_REGEXP="^https://github\\.com/${REPO_SLUG}/\\.github/workflows/release\\.yml@refs/(heads/main|tags/v.*)\$"
MOBILE_IDENTITY_REGEXP="^https://github\\.com/${REPO_SLUG}/\\.github/workflows/mobile-release\\.yml@refs/(heads/main|tags/v.*)\$"

log() { printf '\033[1;34m[verify-release]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[verify-release] FAIL:\033[0m %s\n' "$*" >&2; exit 1; }

if [ "$#" -ne 1 ] || [ -z "${1:-}" ]; then
  fail "usage: $0 <version>  (e.g. $0 1.25.0 or $0 v1.25.0)"
fi

RAW_VERSION="$1"
VERSION="${RAW_VERSION#v}"          # bare X.Y.Z — Docker tags carry no 'v'
TAG="v${VERSION}"                    # vX.Y.Z — GitHub release tag / asset URL

command -v cosign >/dev/null 2>&1 \
  || fail "cosign not found on PATH — install it: https://docs.sigstore.dev/cosign/installation/"
command -v curl >/dev/null 2>&1 \
  || fail "curl not found on PATH"

FAILURES=0
note_failure() {
  FAILURES=$((FAILURES + 1))
  printf '\033[1;31m[verify-release] FAIL:\033[0m %s\n' "$*" >&2
}

verify_image_signature() {
  local image_ref="$1"
  log "verifying signature: ${image_ref}"
  if ! cosign verify \
        --certificate-identity-regexp "$RELEASE_IDENTITY_REGEXP" \
        --certificate-oidc-issuer "$ISSUER" \
        "$image_ref" >/dev/null 2>&1; then
    note_failure "no valid Cosign signature on ${image_ref} for identity ${RELEASE_IDENTITY_REGEXP}"
    return 1
  fi
  log "  signature OK"
}

verify_image_sbom() {
  local image_ref="$1"
  log "verifying SBOM attestation: ${image_ref}"
  if ! cosign verify-attestation \
        --type spdxjson \
        --certificate-identity-regexp "$RELEASE_IDENTITY_REGEXP" \
        --certificate-oidc-issuer "$ISSUER" \
        "$image_ref" >/dev/null 2>&1; then
    note_failure "no valid SBOM attestation on ${image_ref} for identity ${RELEASE_IDENTITY_REGEXP}"
    return 1
  fi
  log "  SBOM attestation OK"
}

verify_apk() {
  local workdir apk bundle base_url
  workdir="$(mktemp -d)"
  trap 'rm -rf "$workdir"' RETURN
  base_url="https://github.com/${REPO_SLUG}/releases/download/${TAG}"
  apk="${workdir}/app-release.apk"
  bundle="${workdir}/app-release.apk.sigstore.json"

  log "downloading APK + Sigstore bundle for ${TAG}"
  if ! curl -fsSL -o "$apk" "${base_url}/app-release.apk"; then
    note_failure "could not download ${base_url}/app-release.apk"
    return 1
  fi
  if ! curl -fsSL -o "$bundle" "${base_url}/app-release.apk.sigstore.json"; then
    note_failure "could not download ${base_url}/app-release.apk.sigstore.json — release may predate S-2 signing"
    return 1
  fi

  log "verifying APK signature"
  if ! cosign verify-blob \
        --bundle "$bundle" \
        --certificate-identity-regexp "$MOBILE_IDENTITY_REGEXP" \
        --certificate-oidc-issuer "$ISSUER" \
        "$apk" >/dev/null 2>&1; then
    note_failure "no valid Cosign signature on the APK for identity ${MOBILE_IDENTITY_REGEXP}"
    return 1
  fi
  log "  APK signature OK"
}

log "verifying WhatIsUp release ${TAG} (image tag ${VERSION})"

verify_image_signature "ghcr.io/${REPO_OWNER}/whatisup-server:${VERSION}" || true
verify_image_sbom "ghcr.io/${REPO_OWNER}/whatisup-server:${VERSION}" || true
verify_image_signature "ghcr.io/${REPO_OWNER}/whatisup-probe:${VERSION}" || true
verify_image_sbom "ghcr.io/${REPO_OWNER}/whatisup-probe:${VERSION}" || true
verify_apk || true

if [ "$FAILURES" -gt 0 ]; then
  fail "${FAILURES} check(s) failed — do NOT deploy this release without investigating (see SECURITY.md)."
fi

log "all checks passed — server image, probe image and APK are signed by this repository's release CI."
