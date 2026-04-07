# WhatIsUp — Launch Posts (ready to publish)

Use these posts to share WhatIsUp on various platforms. Adapt the tone as needed.

---

## GitHub — repo description (updated)

**Short description:**
> Open-source uptime monitoring: multi-probe geographic correlation, browser scenario recorder, real-time dashboard, teams RBAC, SSO/OIDC, public status pages. One Docker command to deploy.

**Topics to add:**
`uptime-monitoring`, `status-page`, `incident-management`, `playwright`, `alerting`, `self-hosted`, `slo`, `devops`, `infrastructure-monitoring`, `open-source`

---

## Reddit — r/selfhosted

**Title:** I built an open-source uptime monitor with multi-probe geographic correlation and a browser scenario recorder — looking for feedback

**Body:**

Hey r/selfhosted,

I've been building **WhatIsUp**, an open-source (MIT) uptime monitoring platform, and I'd love to get your feedback before pushing further.

**The problem I wanted to solve:** most self-hosted monitoring tools either lack geographic correlation (is the site down *everywhere* or just from *here*?) or require a paid SaaS for browser-based scenario checks. I wanted both in a single self-hosted stack.

**What it does:**

- **12 check types** — HTTP/SSL, TCP, UDP, DNS, SMTP, Ping, Domain expiry, Keyword, JSON Path, Browser scenarios (Playwright), Composite monitors, Heartbeat/cron
- **Multi-probe architecture** — deploy lightweight probe agents anywhere (VPS, Raspberry Pi, office LAN); outages are correlated geographically on a world map
- **Browser scenario recorder** — Chrome extension that records your clicks and form fills, then sends the scenario directly as a monitor. Passwords are Fernet-encrypted at rest
- **Real-time dashboard** — WebSocket push, no polling. Dark/light theme
- **Smart alerting** — Email, Webhook (HMAC), Telegram, Slack, PagerDuty, Opsgenie. Flapping detection, alert storm protection, monitor dependencies to suppress cascading alerts, digest mode
- **Public status pages** — shareable `/status/slug` URL with 90-day history bars and email subscriptions
- **Teams & RBAC** — 4 roles (owner/admin/editor/viewer), team-scoped resources
- **SSO/OIDC** — connect Keycloak, Authentik, Auth0, Google... configurable from the admin UI, no restart
- **SLO tracking** — error budget, burn rate, SLA reports with P95 response time
- **Infrastructure-as-Code** — export/import your full config as JSON with diff and dry-run
- **One-command deploy** — `bash deploy.sh` interactive wizard generates secrets, `.env`, TLS certs, starts everything

**Stack:** FastAPI + Vue 3 + PostgreSQL + Redis. Probe agents are standalone Docker containers.

**Quick start:**
```bash
git clone https://github.com/AurevLan/WhatIsUp.git
cd WhatIsUp && docker compose up -d
# Frontend: http://localhost:5173 — API: http://localhost:8000
```

I'm especially looking for feedback on:
- What's missing for your use case?
- Is the setup process smooth enough?
- Any check types you'd want that aren't there?

GitHub: https://github.com/AurevLan/WhatIsUp

Thanks for taking the time!

---

## Reddit — r/devops

**Title:** Open-source multi-probe monitoring with geographic correlation, SLO tracking, and IaC config export — feedback welcome

**Body:**

I've been working on **WhatIsUp**, an open-source (MIT) uptime monitoring platform designed for teams that need geographic outage correlation and don't want to pay for Datadog Synthetics or Checkly.

**Key differentiators:**

1. **Multi-probe correlation** — deploy probe agents in different regions/networks. When a monitor fails, you see *which* probes detect the failure on a world map. Internal vs external network tagging helps distinguish LAN issues from public outages
2. **Browser scenarios** — Playwright-based multi-step checks (login flows, checkout funnels) with Core Web Vitals. A Chrome extension records your actions and creates the scenario in one click
3. **Smart incident pipeline** — flapping detection, monitor dependencies (parent down = children suppressed), incident grouping (same failing probes within 90s = one notification), alert storm protection with forced digest
4. **Infrastructure-as-Code** — `GET /api/v1/config` exports everything as JSON, `PUT /api/v1/config` imports declaratively with diff, dry-run, and prune. Version your monitoring config in git
5. **Teams RBAC + OIDC SSO** — 4 roles, team-scoped resources, configurable from the UI

Stack: FastAPI, Vue 3, PostgreSQL, Redis, Playwright. 215+ tests. MIT licensed.

Looking for feedback from people who run monitoring in production — what would make this useful for your setup?

GitHub: https://github.com/AurevLan/WhatIsUp

---

## Reddit — r/homelab

**Title:** Self-hosted uptime monitoring with a world map of your probes and a Chrome extension to record browser checks

**Body:**

Sharing a project I've been building: **WhatIsUp** — a self-hosted uptime monitoring platform.

The thing I'm most proud of: you can deploy tiny probe agents on any machine (even a Raspberry Pi, 256 MB RAM is enough for basic checks), and the dashboard shows a live world map with per-probe uptime. You see at a glance if your site is down from Paris but up from Tokyo.

Other things homelabbers might like:
- **12 check types** including DNS drift detection, domain expiry alerts, SMTP banner checks, and Playwright browser scenarios
- **Chrome extension** that records your browsing and turns it into a monitoring scenario (great for checking if your Nextcloud login still works)
- **Public status pages** you can share with family/friends who use your services
- **Heartbeat monitoring** — `curl` a URL from your cron jobs, get alerted if they stop
- **Dark/light theme**, English/French
- Runs on a 2 GB RAM VPS with Docker Compose

```bash
git clone https://github.com/AurevLan/WhatIsUp.git
cd WhatIsUp && docker compose up -d
```

MIT licensed, no telemetry, no SaaS dependency.

GitHub: https://github.com/AurevLan/WhatIsUp

What checks would you want for your homelab setup?

---

## Hacker News — Show HN

**Title:** Show HN: WhatIsUp -- Open-source uptime monitoring with multi-probe geographic correlation

**Body:**

WhatIsUp is an open-source (MIT) uptime monitoring platform I built because I wanted geographic outage correlation and browser scenario checks without paying for a SaaS.

Key ideas:

- Deploy lightweight probe agents anywhere. The dashboard correlates failures geographically on a world map, so you see if an outage is local or global.

- A Chrome extension records your browser actions (clicks, form fills, navigations) and sends them as a Playwright-based monitoring scenario. Passwords are Fernet-encrypted at rest and only decrypted when delivered to the probe.

- The incident pipeline groups monitors that fail on the same probes within 90 seconds into a single incident group. Monitor dependencies suppress cascading alerts. Alert storm protection forces digest mode when a threshold is exceeded.

- Full config can be exported/imported as JSON (IaC-style) with diff and dry-run.

Stack: FastAPI, Vue 3, PostgreSQL, Redis. 215+ tests. One-command Docker deploy.

https://github.com/AurevLan/WhatIsUp

I'm looking for feedback on what's missing, what's rough, and what would make this useful for your setup.

---

## Twitter/X

**Post 1 (launch):**

I built an open-source uptime monitor with geographic outage correlation.

Deploy probe agents anywhere. See on a world map where your site is down. Record browser scenarios with a Chrome extension. Smart alerting that suppresses cascading alerts.

MIT licensed. One Docker command.

github.com/AurevLan/WhatIsUp

**Post 2 (feature focus):**

Most monitoring tools tell you "your site is down."

WhatIsUp tells you "your site is down from Paris and London, but up from Tokyo and New York — it's probably your EU CDN."

Multi-probe geographic correlation, open-source, self-hosted.

github.com/AurevLan/WhatIsUp

**Post 3 (scenario recorder):**

I built a Chrome extension that records your browser actions and turns them into uptime monitoring scenarios.

Click around your app. Stop recording. One click to send to WhatIsUp. Passwords auto-encrypted.

No more writing Playwright scripts by hand for synthetic monitoring.

github.com/AurevLan/WhatIsUp

---

## LinkedIn

**WhatIsUp — Open-source uptime monitoring with geographic intelligence**

After months of development, I'm sharing WhatIsUp, an open-source (MIT) monitoring platform I built to solve a gap I kept hitting: knowing not just *if* a service is down, but *where* it's down.

The core idea: deploy lightweight probe agents across your infrastructure — datacenters, offices, edge locations — and correlate failures geographically. The dashboard shows a live world map with per-probe health, so you immediately see if an outage is regional or global.

What makes it different:
- Browser scenario monitoring via a Chrome extension recorder (Playwright under the hood)
- Smart incident grouping that reduces alert fatigue — cascading failures trigger one notification, not fifty
- Infrastructure-as-Code: export and version your entire monitoring config as JSON
- Teams with RBAC and SSO/OIDC support
- Public status pages for external communication

Built with FastAPI, Vue 3, PostgreSQL, and Redis. 215+ tests. Deploys in one command with Docker.

I'm actively looking for feedback from SREs, DevOps engineers, and platform teams. What would make this useful in your environment?

GitHub: https://github.com/AurevLan/WhatIsUp

#opensource #monitoring #devops #sre #uptime #selfhosted

---

## Suggested posting order

1. **GitHub** — update description + topics
2. **r/selfhosted** — largest audience for self-hosted tools
3. **Hacker News (Show HN)** — best on a weekday morning US time (Tuesday-Thursday, 10-11am ET)
4. **r/devops** — more technical audience
5. **r/homelab** — enthusiast audience
6. **Twitter/X** — spread over 3 days (one post per day)
7. **LinkedIn** — professional network

## Tips

- Post on HN Tuesday-Thursday between 10-11am ET for best visibility
- On Reddit, engage with every comment in the first 2 hours
- Add screenshots/GIFs to Reddit posts when possible (dashboard, probe map, scenario recorder)
- Cross-post to r/opensource after getting traction on r/selfhosted
- Consider posting to Lobsters (lobste.rs) if you have an invite
- Add the project to awesome-selfhosted (https://github.com/awesome-selfhosted/awesome-selfhosted) via PR
