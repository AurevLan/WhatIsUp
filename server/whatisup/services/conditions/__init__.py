"""Alert condition plugin system — registry and lookup.

Usage::

    from whatisup.services.conditions import CONDITION_REGISTRY, get_handler

Every ``AlertCondition`` member must have a handler: ``test_condition_registry``
fails the build otherwise, which is what stops a new condition from shipping
with a dispatch path and no preview (or the reverse).

See ``base.py`` for why this layer exists at all.
"""

from __future__ import annotations

from whatisup.models.alert import AlertCondition

from .availability import AllDownHandler, AnyDownHandler
from .base import (
    AlertConditionHandler,
    DispatchContext,
    DispatchDecision,
    PreviewContext,
    PreviewResult,
)
from .integrity import SchemaDriftHandler, SslExpiryHandler
from .latency import (
    AnomalyDetectionHandler,
    ResponseTimeAboveBaselineHandler,
    ResponseTimeAboveHandler,
)
from .metrics import MetricAboveHandler, MetricAbsentHandler, MetricBelowHandler

__all__ = [
    "CONDITION_REGISTRY",
    "AlertConditionHandler",
    "DispatchContext",
    "DispatchDecision",
    "PreviewContext",
    "PreviewResult",
    "get_handler",
    "needs_check_result",
]

_HANDLERS: tuple[AlertConditionHandler, ...] = (
    AnyDownHandler(),
    AllDownHandler(),
    SslExpiryHandler(),
    ResponseTimeAboveHandler(),
    ResponseTimeAboveBaselineHandler(),
    AnomalyDetectionHandler(),
    SchemaDriftHandler(),
    MetricAboveHandler(),
    MetricBelowHandler(),
    MetricAbsentHandler(),
)

CONDITION_REGISTRY: dict[AlertCondition, AlertConditionHandler] = {
    handler.condition: handler for handler in _HANDLERS
}


def get_handler(condition: AlertCondition | str) -> AlertConditionHandler | None:
    """Handler for a condition, or None if it has none.

    Accepts the raw string as well: rules arrive both as ORM objects (enum) and
    as matrix payload rows (string).
    """
    if isinstance(condition, str) and not isinstance(condition, AlertCondition):
        try:
            condition = AlertCondition(condition)
        except ValueError:
            return None
    return CONDITION_REGISTRY.get(condition)


def needs_check_result(condition: AlertCondition | str) -> bool:
    """Whether this condition's verdict is read off a ``CheckResult``.

    Lets callers skip fetching the latest results entirely — on a partitioned
    ``check_results`` that query is anything but free.
    """
    handler = get_handler(condition)
    return handler.needs_check_result if handler else False
