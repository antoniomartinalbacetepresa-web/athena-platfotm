from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.api.auth import current_account
from app.main import app
from app.security.portfolio_owner_context import portfolio_owner_scope


_TEST_OWNER = 101


@pytest.fixture(autouse=True)
def _owner_context_for_professional_portfolio_tests(request: pytest.FixtureRequest) -> Iterator[None]:
    module_name = str(getattr(request.module, "__name__", "")).rsplit(".", 1)[-1]
    if not module_name.startswith("test_recommendation_portfolio"):
        yield
        return

    previous = app.dependency_overrides.get(current_account)
    app.dependency_overrides[current_account] = lambda: {
        "id": _TEST_OWNER,
        "email": "portfolio-test@example.com",
    }
    try:
        # API requests establish their own owner context through the JWT-derived
        # router dependency. Only direct NLV repository tests need an explicit
        # trusted scope; keeping TWR core tests ownerless preserves their lower-
        # level sealing/tamper contract without weakening the HTTP boundary.
        if "nlv_snapshot_repository" in module_name:
            with portfolio_owner_scope(_TEST_OWNER):
                yield
        else:
            yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(current_account, None)
        else:
            app.dependency_overrides[current_account] = previous
