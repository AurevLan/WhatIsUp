"""Integrity conditions — the endpoint answers, but not with what it should.

TLS certificate validity/expiry and JSON response-shape drift. Neither is an
outage: the check is ``up`` in both cases, which is exactly why they need their
own conditions rather than riding on ``any_down``.
"""

from __future__ import annotations

from whatisup.models.alert import AlertCondition
from whatisup.services.alert_conditions import schema_drift_matches, ssl_expiry_matches

from .base import (
    AlertConditionHandler,
    DispatchContext,
    DispatchDecision,
    PreviewContext,
    PreviewResult,
)


class SslExpiryHandler(AlertConditionHandler):
    condition = AlertCondition.ssl_expiry

    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        fire = ssl_expiry_matches(
            dispatch.result.ssl_valid,
            dispatch.result.ssl_days_remaining,
            dispatch.monitor.ssl_expiry_warn_days,
        )
        return DispatchDecision(fire=fire)

    async def preview(self, preview: PreviewContext) -> PreviewResult:
        expiring = []
        for mid in preview.monitor_ids:
            result = preview.latest.get(mid)
            if result is None:
                continue
            monitor = preview.monitors_by_id[mid]
            # Per-monitor warn window, not a hardcoded 30 days: the preview used
            # to invent its own and disagree with what actually pages.
            if not ssl_expiry_matches(
                result.ssl_valid, result.ssl_days_remaining, monitor.ssl_expiry_warn_days
            ):
                continue
            if result.ssl_valid is False:
                expiring.append(f"{monitor.name} (certificat invalide)")
            else:
                expiring.append(f"{monitor.name} (expire dans {result.ssl_days_remaining}j)")

        reason = (
            f"Certificat(s) SSL invalide(s) ou expirant bientôt : {', '.join(expiring)}"
            if expiring
            else "Tous les certificats SSL sont valides (hors fenêtre d'alerte)"
        )
        return PreviewResult(would_fire=bool(expiring), reason=reason, affected=expiring)


class SchemaDriftHandler(AlertConditionHandler):
    condition = AlertCondition.schema_drift

    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        fingerprint = dispatch.result.schema_fingerprint
        baseline = dispatch.monitor.schema_baseline
        if not schema_drift_matches(fingerprint, baseline):
            return DispatchDecision.no()
        return DispatchDecision.yes(schema_fingerprint=fingerprint, schema_baseline=baseline)

    async def preview(self, preview: PreviewContext) -> PreviewResult:
        drifted = []
        missing_baseline = 0
        for mid in preview.monitor_ids:
            baseline = preview.monitors_by_id[mid].schema_baseline
            if not baseline:
                # No baseline recorded means detection was never enabled on the
                # monitor — the rule is inert, and saying so is the difference
                # between a fixable message and a dead end.
                missing_baseline += 1
                continue
            result = preview.latest.get(mid)
            if result is not None and schema_drift_matches(result.schema_fingerprint, baseline):
                drifted.append(preview.monitors_by_id[mid].name)

        if drifted:
            reason = f"Dérive de schéma détectée sur : {', '.join(drifted)}"
        elif missing_baseline == len(preview.monitor_ids):
            reason = "Aucune baseline de schéma enregistrée — la règle ne peut pas se déclencher"
        else:
            reason = "Aucune dérive de schéma par rapport à la baseline"
        return PreviewResult(would_fire=bool(drifted), reason=reason, affected=drifted)
