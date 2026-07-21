"""Monitor endpoints, split into sub-routers (R-3).

Each submodule carries its own ``APIRouter(prefix="/monitors")`` and
``main.py`` includes them all at the first level — a single aggregated
router would add a second ``_IncludedRouter`` nesting level (FastAPI
>=0.138 lazy include) and strip the ``/monitors`` prefix from the inner
``APIRoute.path``s, breaking the routing-table introspection in
``test_rate_limit_coverage.py``.

``routers`` order matters: routers carrying single-segment static paths
(``GET /export``, ``GET /graph``) must register before ``crud``'s
``GET /{monitor_id}``, or FastAPI would try to parse "export"/"graph"
as a monitor UUID (422).
"""

from whatisup.api.v1.monitors import (
    annotations,
    baselines,
    crud,
    dependencies,
    health,
    import_export,
    incidents,
    stats,
)
from whatisup.api.v1.monitors.crud import create_monitor, list_monitors

__all__ = ["create_monitor", "list_monitors", "routers"]

routers = (
    import_export.router,
    dependencies.router,
    crud.router,
    stats.router,
    health.router,
    incidents.router,
    annotations.router,
    baselines.router,
)
