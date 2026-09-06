"""SQLAlchemy models — import all to ensure Alembic autogenerate picks them up."""

from whatisup.models.alert import (
    AlertChannel,
    AlertChannelType,
    AlertCondition,
    AlertEvent,
    AlertEventStatus,
    AlertRule,
)
from whatisup.models.alert_matrix_template import AlertMatrixTemplate
from whatisup.models.annotation import MonitorAnnotation
from whatisup.models.api_key import UserApiKey
from whatisup.models.audit_log import AuditLog
from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from whatisup.models.correlation_pattern import CorrelationPattern
from whatisup.models.custom_metric import CustomMetric, MetricSeries
from whatisup.models.device_token import DevicePlatform, DeviceToken
from whatisup.models.digest_window import DigestWindow
from whatisup.models.discovery import (
    DISCOVERED_SERVICE_STATUSES,
    DiscoveredService,
    DiscoverySource,
)
from whatisup.models.incident import Incident, IncidentGroup, IncidentScope
from whatisup.models.incident_diagnostic import DIAGNOSTIC_KINDS, IncidentDiagnostic
from whatisup.models.incident_update import IncidentUpdate, IncidentUpdateStatus
from whatisup.models.maintenance import MaintenanceWindow
from whatisup.models.monitor import (
    CompositeMonitorMember,
    Monitor,
    MonitorDependency,
    MonitorGroup,
)
from whatisup.models.monitor_health import MonitorHealthState, SLORule, SLORuleType
from whatisup.models.monitor_template import MonitorTemplate
from whatisup.models.oncall import (
    ContactMethod,
    EscalationLevel,
    EscalationPolicy,
    EscalationState,
    EscalationTargetType,
    OnCallOverride,
    OnCallParticipant,
    OnCallSchedule,
    RotationType,
    UserContact,
)
from whatisup.models.probe import Probe
from whatisup.models.probe_group import ProbeGroup, probe_group_members, user_probe_group_access
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.rollup import CheckRollup1h
from whatisup.models.silence import AlertSilence
from whatisup.models.status_announcement import StatusAnnouncement, StatusAnnouncementUpdate
from whatisup.models.status_subscription import StatusSubscription
from whatisup.models.system_settings import SystemSettings
from whatisup.models.tag import Tag
from whatisup.models.team import Team, TeamMembership, TeamRole
from whatisup.models.user import User
from whatisup.models.web_push import WebPushSubscription

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "Tag",
    "CompositeMonitorMember",
    "Monitor",
    "MonitorDependency",
    "MonitorGroup",
    "Probe",
    "ProbeGroup",
    "probe_group_members",
    "user_probe_group_access",
    "CheckResult",
    "CheckStatus",
    "CheckRollup1h",
    "CustomMetric",
    "MetricSeries",
    "Incident",
    "IncidentGroup",
    "IncidentScope",
    "IncidentDiagnostic",
    "DIAGNOSTIC_KINDS",
    "AlertChannel",
    "AlertChannelType",
    "AlertCondition",
    "AlertEvent",
    "AlertEventStatus",
    "AlertRule",
    "AlertMatrixTemplate",
    "AlertSilence",
    "AuditLog",
    "MaintenanceWindow",
    "CorrelationPattern",
    "DigestWindow",
    "DiscoverySource",
    "DiscoveredService",
    "DISCOVERED_SERVICE_STATUSES",
    "MonitorAnnotation",
    "StatusAnnouncement",
    "StatusAnnouncementUpdate",
    "StatusSubscription",
    "SystemSettings",
    "UserApiKey",
    "IncidentUpdate",
    "IncidentUpdateStatus",
    "MonitorHealthState",
    "SLORule",
    "SLORuleType",
    "MonitorTemplate",
    "Team",
    "ContactMethod",
    "EscalationLevel",
    "EscalationPolicy",
    "EscalationState",
    "EscalationTargetType",
    "OnCallOverride",
    "OnCallParticipant",
    "OnCallSchedule",
    "RotationType",
    "UserContact",
    "TeamMembership",
    "TeamRole",
    "WebPushSubscription",
    "DeviceToken",
    "DevicePlatform",
]
