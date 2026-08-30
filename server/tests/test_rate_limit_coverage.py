"""S2 — regression guard for API-wide rate-limit coverage.

SECURITY.md §12 requires "Tout nouvel endpoint public ou écrit DOIT avoir un
rate-limit explicite." This module introspects the live FastAPI app so a
future PR that adds a mutating endpoint without ``@limiter.limit(...)`` fails
CI instead of shipping silently — the exact failure mode of the S2 audit
(``teams.py`` shipped with 9 undecorated endpoints and the limiter not even
imported).

slowapi's ``Limiter.limit`` decorator registers the *original* function under
``limiter._route_limits`` (or ``_dynamic_route_limits`` for callables), keyed
by ``f"{func.__module__}.{func.__name__}"``. Because the decorator wraps with
``functools.wraps``, the route's registered endpoint keeps the same
``__module__``/``__name__``, so we can recover that key straight from the
routing table without importing every router module by hand.

FastAPI >=0.138 (see `project_fastapi_137_router_break.md`) wraps each
``include_router()`` call in an internal ``_IncludedRouter`` lazy-matching
object, so ``app.routes`` no longer yields flat ``APIRoute`` instances for
included sub-routers directly — each wrapper exposes the real sub-router via
``.original_router.routes``, which we walk to rebuild the flat list. Those
inner routes carry the router's own path (e.g. ``/teams/{team_id}``) *without*
the ``/api/v1`` prefix, which is applied by the wrapper at dispatch time — so
comparisons below use the un-prefixed path.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from whatisup.core.limiter import limiter
from whatisup.main import app

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Endpoints intentionally left without an explicit @limiter.limit. Each entry
# must be documented in SECURITY.md §12 with the reason — do not add to this
# set without updating that table too.
_EXEMPT_KEYS = {
    # Probe registration requires an already-authenticated superadmin JWT
    # (get_current_probe is not used here); the JWT auth + require_superadmin
    # gate is the actual control. See SECURITY.md §12 "/probes/register".
    "whatisup.api.v1.probes.register_probe",
}

# Specific endpoints named in the S2 audit — asserted individually so a
# regression on any one of them fails with a precise, readable message rather
# than only showing up in the aggregate scan below.
#
# Paths are the router's *own* path (no "/api/v1" prefix) — see module
# docstring on why the prefix is stripped at this layer.
_MUST_HAVE_LIMIT = [
    ("GET", "/teams/", "whatisup.api.v1.teams.list_teams"),
    ("POST", "/teams/", "whatisup.api.v1.teams.create_team"),
    ("GET", "/teams/{team_id}", "whatisup.api.v1.teams.get_team"),
    ("PATCH", "/teams/{team_id}", "whatisup.api.v1.teams.update_team"),
    ("DELETE", "/teams/{team_id}", "whatisup.api.v1.teams.delete_team"),
    ("GET", "/teams/{team_id}/members", "whatisup.api.v1.teams.list_members"),
    ("POST", "/teams/{team_id}/members", "whatisup.api.v1.teams.add_member"),
    (
        "PATCH",
        "/teams/{team_id}/members/{user_id}",
        "whatisup.api.v1.teams.update_member_role",
    ),
    (
        "DELETE",
        "/teams/{team_id}/members/{user_id}",
        "whatisup.api.v1.teams.remove_member",
    ),
    ("POST", "/alerts/rules", "whatisup.api.v1.alerts.create_rule"),
    ("GET", "/onboarding/status", "whatisup.api.v1.onboarding.get_onboarding_status"),
    ("POST", "/onboarding/complete", "whatisup.api.v1.onboarding.complete_onboarding"),
    ("GET", "/audit/", "whatisup.api.v1.audit.list_audit_logs"),
    ("POST", "/groups/", "whatisup.api.v1.groups.create_group"),
    ("DELETE", "/api-keys/{key_id}", "whatisup.api.v1.api_keys.revoke_api_key"),
    ("POST", "/auth/logout", "whatisup.api.v1.auth.logout"),
    (
        "DELETE",
        "/monitors/{monitor_id}/dependencies/{dependency_id}",
        "whatisup.api.v1.monitors.dependencies.remove_dependency",
    ),
    (
        "DELETE",
        "/monitors/{monitor_id}/composite-members/{member_id}",
        "whatisup.api.v1.monitors.dependencies.remove_composite_member",
    ),
    (
        "GET",
        "/public/pages/{slug}/unsubscribe",
        "whatisup.api.v1.public.unsubscribe_status",
    ),
]


def _is_limited(key: str) -> bool:
    return key in limiter._route_limits or key in limiter._dynamic_route_limits


def _flatten_routes() -> list[APIRoute]:
    """Recursively unwrap ``_IncludedRouter`` wrappers down to ``APIRoute``s.

    See the module docstring: FastAPI >=0.138 no longer exposes included
    sub-router routes directly on ``app.routes``.
    """
    flat: list[APIRoute] = []
    stack = list(app.routes)
    seen: set[int] = set()
    while stack:
        route = stack.pop()
        if id(route) in seen:
            continue
        seen.add(id(route))
        if isinstance(route, APIRoute):
            flat.append(route)
            continue
        sub_router = getattr(route, "original_router", None) or getattr(route, "router", None)
        if sub_router is not None:
            stack.extend(getattr(sub_router, "routes", []))
    return flat


def _v1_routes() -> list[APIRoute]:
    # Every APIRoute in this app belongs to a v1 router mounted under
    # /api/v1 (see whatisup/main.py) — non-API routes (docs, redoc, the
    # openapi schema, websockets) are plain starlette Route/WebSocketRoute
    # instances and are filtered out by the isinstance check in
    # _flatten_routes already.
    return _flatten_routes()


def test_named_s2_endpoints_are_rate_limited() -> None:
    """Every endpoint identified by the S2 audit now carries @limiter.limit."""
    missing = [key for _, _, key in _MUST_HAVE_LIMIT if not _is_limited(key)]
    assert not missing, f"Endpoints still missing @limiter.limit: {missing}"


def test_named_s2_endpoints_exist_in_routing_table() -> None:
    """Guard against the assertion above passing only because a route was
    renamed/removed — cross-check path+method actually resolve to that key."""
    routes_by_path_method = {
        (route.path, method): f"{route.endpoint.__module__}.{route.endpoint.__name__}"
        for route in _v1_routes()
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    mismatches = []
    for method, path, expected_key in _MUST_HAVE_LIMIT:
        actual_key = routes_by_path_method.get((path, method))
        if actual_key != expected_key:
            mismatches.append((method, path, expected_key, actual_key))
    assert not mismatches, f"Route table drift vs test fixtures: {mismatches}"


def test_all_mutating_v1_endpoints_have_rate_limit() -> None:
    """No POST/PUT/PATCH/DELETE endpoint under /api/v1 ships without a limit,
    unless explicitly documented in `_EXEMPT_KEYS` (and SECURITY.md §12)."""
    missing = []
    for route in _v1_routes():
        methods = route.methods - {"HEAD", "OPTIONS"}
        if not methods & _MUTATING_METHODS:
            continue
        key = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
        if key in _EXEMPT_KEYS:
            continue
        if not _is_limited(key):
            missing.append(f"{sorted(methods & _MUTATING_METHODS)} {route.path} -> {key}")

    assert not missing, (
        "Mutating endpoints missing @limiter.limit (add one, or document the "
        "exemption in _EXEMPT_KEYS + SECURITY.md §12):\n" + "\n".join(missing)
    )


def test_all_get_v1_endpoints_have_rate_limit() -> None:
    """SEC-3 — no GET endpoint under /api/v1 ships without a limit either.

    Scoped to ``whatisup.api.v1.*`` modules: ``/api/health`` (LB / probe /
    ServerSetupView health checks) and ``/api/metrics`` (Prometheus scrape)
    live outside the v1 routers and are intentionally unlimited — see
    SECURITY.md §12.
    """
    missing = []
    for route in _v1_routes():
        if "GET" not in route.methods:
            continue
        key = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
        if not key.startswith("whatisup.api.v1."):
            continue
        if key in _EXEMPT_KEYS:
            continue
        if not _is_limited(key):
            missing.append(f"GET {route.path} -> {key}")

    assert not missing, (
        "GET endpoints missing @limiter.limit (add one, or document the "
        "exemption in _EXEMPT_KEYS + SECURITY.md §12):\n" + "\n".join(missing)
    )
