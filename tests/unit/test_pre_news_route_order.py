"""Route-ordering guard for the pre-news router.

FastAPI matches routes in registration order. The dynamic ``/{ticker}`` route
matches any single path segment, so if it is registered before a literal
single-segment route (e.g. ``/baselines``) it silently shadows it and the literal
route returns 404. This locks the catch-all to the end of the router.
"""

import pytest


def _get_paths(router):
    paths = []
    for route in router.routes:
        methods = getattr(route, "methods", set()) or set()
        if "GET" in methods:
            paths.append(route.path)
    return paths


CATCH_ALL = "/agentic/pre-news/{ticker}"


def test_dynamic_ticker_route_is_registered_last():
    from src.api.routes.pre_news import router

    get_paths = _get_paths(router)
    assert get_paths, "pre-news router exposes no GET routes"
    assert get_paths[-1] == CATCH_ALL, (
        "The catch-all '/{ticker}' route must be the last GET route so literal "
        f"single-segment paths match first. Current order: {get_paths}"
    )


@pytest.mark.parametrize("literal", [
    "/agentic/pre-news/baselines",
    "/agentic/pre-news/learning",
    "/agentic/pre-news/anomalies",
    "/agentic/pre-news/evaluation",
])
def test_literal_single_segment_routes_precede_catch_all(literal):
    from src.api.routes.pre_news import router

    get_paths = _get_paths(router)
    assert literal in get_paths, f"expected literal route {literal} to exist"
    assert get_paths.index(literal) < get_paths.index(CATCH_ALL), (
        f"{literal} is shadowed by '/{{ticker}}' — it must be registered first."
    )
