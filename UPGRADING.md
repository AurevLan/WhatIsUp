# Upgrading to WhatIsUp v1.0.0

This guide covers migrating from v0.12.x to v1.0.0.

## Breaking changes

None. v1.0.0 is fully backward-compatible with v0.12.x data and APIs.

## New features requiring migration

### Database migration

Run Alembic migrations after upgrading the server image:

```bash
docker compose exec server alembic upgrade head
```

Two new migrations will run:
- `m1n2o3p4q5r6` — Creates `teams` and `team_memberships` tables, adds `team_id` column to monitors, groups, channels, maintenance windows, and templates
- `n1o2p3q4r5s6` — Adds `onboarding_completed_at` column to users

### Teams (optional)

Teams are opt-in. Existing installations continue to work exactly as before with single-user ownership. To start using teams:

1. Any user can create a team via `POST /api/v1/teams`
2. The creator becomes the team owner
3. Invite members with `POST /api/v1/teams/{id}/members`
4. Assign resources to teams by setting `team_id` when creating monitors, groups, or alert channels

Team roles: `owner` > `admin` > `editor` > `viewer`

### Onboarding wizard

New users (with no monitors and `onboarding_completed_at = NULL`) will see an onboarding wizard on first login. Existing users with monitors are unaffected.

### Infrastructure-as-Code API

New endpoints for declarative configuration management:
- `GET /api/v1/config` — Export full config as JSON
- `PUT /api/v1/config` — Import declarative config (diff + apply)
- `PUT /api/v1/config?dry_run=true` — Preview changes without applying

### Plugin architecture (internal)

The checker and alert channel dispatch has been refactored into a plugin system. This is an internal change — the API is unchanged. Custom check types and alert channels can now be added by creating a module in the `checkers/` or `channels/` package.

### Light theme

A light theme is now available. Toggle via the sun/moon button in the top bar. The theme is auto-detected from `prefers-color-scheme` on first visit and persisted in `localStorage`.

## Docker upgrade

```bash
docker compose pull
docker compose up -d
# Migrations run automatically on server startup
```

## API stability commitment

Starting with v1.0.0, the `/api/v1/` endpoints are considered stable. Breaking changes will be introduced under `/api/v2/` with a 6-month deprecation period for v1 endpoints.
