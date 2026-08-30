"""Alert channel and rule endpoints, split into sub-routers.

Each submodule carries its own ``APIRouter(prefix="/alerts")`` and
``main.py`` includes them all at the first level — a single aggregated
router would add a second ``_IncludedRouter`` nesting level (FastAPI
>=0.138 lazy include) and strip the ``/alerts`` prefix from the inner
``APIRoute.path``s, breaking the routing-table introspection in
``test_rate_limit_coverage.py``.

``routers`` order matters relative to the original ``alerts.py`` layout —
channels, then rules (+ events/presets/auto-rules), then the matrix
(+ templates), then threshold suggestions — even though every route here
starts on a distinct static segment, so there's no actual static/param
collision risk to order against.
"""

from whatisup.api.v1.alerts import channels, matrix, rules, suggestions
from whatisup.api.v1.alerts._common import _fetch_channels_by_ids
from whatisup.api.v1.alerts.matrix import _MATRIX_RULE_FIELDS

__all__ = ["_MATRIX_RULE_FIELDS", "_fetch_channels_by_ids", "routers"]

routers = (
    channels.router,
    rules.router,
    matrix.router,
    suggestions.router,
)
