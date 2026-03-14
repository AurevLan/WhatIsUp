"""SQLAlchemy models — import all to ensure Alembic autogenerate picks them up."""

from whatisup.models.alert import (
    AlertChannel,
    AlertChannelType,
    AlertCondition,
    AlertEvent,
    AlertEventStatus,
    AlertRule,
)
from whatisup.models.annotation import MonitorAnnotation
from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from whatisup.models.custom_metric import CustomMetric
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor, MonitorGroup, PublicPage
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.status_subscription import StatusSubscription
from whatisup.models.tag import PermissionLevel, Tag, UserTagPermission
from whatisup.models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "Tag",
    "UserTagPermission",
    "PermissionLevel",
    "Monitor",
    "MonitorGroup",
    "PublicPage",
    "Probe",
    "CheckResult",
    "CheckStatus",
    "CustomMetric",
    "Incident",
    "IncidentScope",
    "AlertChannel",
    "AlertChannelType",
    "AlertCondition",
    "AlertEvent",
    "AlertEventStatus",
    "AlertRule",
    "MonitorAnnotation",
    "StatusSubscription",
]
