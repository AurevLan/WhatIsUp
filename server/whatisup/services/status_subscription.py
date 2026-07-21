"""Status-page email subscriptions — double opt-in and incident notifications.

Avant ce module, `StatusSubscription` était une impasse : la table se
remplissait mais n'était relue nulle part. Personne ne recevait donc jamais
de mail, et comme le jeton de désinscription n'était délivré par aucun canal,
l'endpoint d'unsubscribe restait inatteignable en pratique.

Deux règles structurent le module :

* **Double opt-in.** Une inscription naît non confirmée. Sans cela, n'importe
  qui pouvait abonner l'adresse d'un tiers à une page publique — la page ne
  demande aucune authentification.
* **Lien de désinscription dans chaque mail.** C'est la seule voie par
  laquelle le jeton atteint son destinataire.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.status_subscription import StatusSubscription

logger = logging.getLogger(__name__)


def _public_url(path: str) -> str:
    """URL absolue d'une page publique, pour les liens des e-mails."""
    base = str(get_settings().public_base_url).rstrip("/")
    return f"{base}{path}"


async def _send_mail(to: str, subject: str, body: str) -> bool:
    """Envoi best-effort : un mail perdu ne doit pas casser l'appelant.

    Le pipeline d'incident appelle ce module ; une panne SMTP ne doit ni
    interrompre la résolution d'un incident, ni empêcher les autres abonnés
    d'être prévenus.
    """
    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = str(settings.smtp_from)
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            start_tls=settings.smtp_tls,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            timeout=15,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort, voir docstring
        logger.warning("status_subscription_mail_failed", exc_info=exc)
        return False


async def send_confirmation_email(sub: StatusSubscription, group: MonitorGroup) -> bool:
    """Mail de double opt-in : sans clic, l'inscription reste inactive."""
    # Query param sur la page de statut existante plutôt qu'une sous-route :
    # le routeur frontend n'expose que `/status/:slug`, une sous-route serait
    # avalée par le catch-all.
    confirm_url = _public_url(f"/status/{group.public_slug}?confirm={sub.confirm_token}")
    body = (
        f"Someone asked to receive status updates for “{group.name}”.\n\n"
        f"Confirm your subscription:\n{confirm_url}\n\n"
        "If this wasn't you, ignore this email — no subscription is active "
        "until the link above is used."
    )
    return await _send_mail(
        sub.email,
        f"[WhatIsUp] Confirm your subscription to {group.name}",
        body,
    )


def _incident_body(group: MonitorGroup, monitor_name: str, resolved: bool, sub_token: str) -> str:
    page_url = _public_url(f"/status/{group.public_slug}")
    unsub_url = _public_url(f"/status/{group.public_slug}?unsubscribe={sub_token}")
    headline = f"{monitor_name} is back up." if resolved else f"{monitor_name} is currently down."
    return f"{headline}\n\nStatus page: {page_url}\n\n---\nUnsubscribe: {unsub_url}"


async def notify_subscribers(
    db: AsyncSession,
    monitor: Monitor,
    *,
    resolved: bool,
) -> int:
    """Prévient les abonnés confirmés de la page publique du groupe du monitor.

    Ne fait rien — sans requête inutile — si le monitor n'appartient à aucun
    groupe publié. Renvoie le nombre de mails effectivement partis.
    """
    if monitor.group_id is None:
        return 0

    group = (
        await db.execute(
            select(MonitorGroup).where(
                MonitorGroup.id == monitor.group_id,
                MonitorGroup.public_slug.isnot(None),
            )
        )
    ).scalar_one_or_none()
    if group is None:
        return 0

    subs = (
        (
            await db.execute(
                select(StatusSubscription).where(
                    StatusSubscription.group_id == group.id,
                    StatusSubscription.confirmed_at.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not subs:
        return 0

    sent = 0
    subject_state = "resolved" if resolved else "down"
    for sub in subs:
        ok = await _send_mail(
            sub.email,
            f"[WhatIsUp] {group.name} — {monitor.name} {subject_state}",
            _incident_body(group, monitor.name, resolved, sub.token),
        )
        if ok:
            sent += 1
    return sent
