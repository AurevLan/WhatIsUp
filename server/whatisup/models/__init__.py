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
from whatisup.models.api_key import UserApiKey
from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from whatisup.models.correlation_pattern import CorrelationPattern
from whatisup.models.custom_metric import CustomMetric
from whatisup.models.incident import Incident, IncidentGroup, IncidentScope
from whatisup.models.incident_update import IncidentUpdate, IncidentUpdateStatus
from whatisup.models.monitor import (
    CompositeMonitorMember,
    Monitor,
    MonitorDependency,
    MonitorGroup,
    PublicPage,
)
from whatisup.models.monitor_template import MonitorTemplate
from whatisup.models.probe import Probe
from whatisup.models.probe_group import ProbeGroup, probe_group_members, user_probe_group_access
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.status_subscription import StatusSubscription
from whatisup.models.system_settings import SystemSettings
from whatisup.models.tag import PermissionLevel, Tag, UserTagPermission
from whatisup.models.team import Team, TeamMembership, TeamRole
from whatisup.models.user import User
from whatisup.models.web_push import WebPushSubscription

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "Tag",
    "UserTagPermission",
    "PermissionLevel",
    "CompositeMonitorMember",
    "Monitor",
    "MonitorDependency",
    "MonitorGroup",
    "PublicPage",
    "Probe",
    "ProbeGroup",
    "probe_group_members",
    "user_probe_group_access",
    "CheckResult",
    "CheckStatus",
    "CustomMetric",
    "Incident",
    "IncidentGroup",
    "IncidentScope",
    "AlertChannel",
    "AlertChannelType",
    "AlertCondition",
    "AlertEvent",
    "AlertEventStatus",
    "AlertRule",
    "CorrelationPattern",
    "MonitorAnnotation",
    "StatusSubscription",
    "SystemSettings",
    "UserApiKey",
    "IncidentUpdate",
    "IncidentUpdateStatus",
    "MonitorTemplate",
    "Team",
    "TeamMembership",
    "TeamRole",
    "WebPushSubscription",
]
