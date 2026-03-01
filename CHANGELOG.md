# Changelog

All notable changes to WhatIsUp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-02-28

### Added
- HTTP/HTTPS URL monitoring with redirect following
- SSL certificate monitoring (validity, expiry warning)
- Multi-probe architecture with geographic correlation
  - Probes push results to central API via HTTPS
  - Global vs geographic incident detection
- Multi-user authentication with JWT (access + refresh tokens)
- Role-based access via tags (view/edit/admin per tag)
- Monitor groups with optional public status pages
- Alert channels: Email (SMTP), Webhook (HMAC-signed), Telegram Bot API
- Alert rules per monitor or group with configurable conditions
- Real-time WebSocket updates for dashboard and public pages
- REST API for external monitoring tool integration
- External status API (`/api/v1/status/monitors`)
- Vue.js 3 + Vite frontend with Tailwind CSS
- ApexCharts response time timeline
- Docker Compose (dev + prod with Nginx)
- Security: rate limiting, security headers, JWT validation, probe API key hashing
