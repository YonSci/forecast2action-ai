"""Builds OperationalContext from request parameters.

Fields the app has no real data source for (available_resources,
resource_constraints, access_constraints, communication_channels,
existing_active_actions, coordination_status -- there is no resource-
tracking system in this app yet) are deliberately left out of
OperationalContext entirely rather than populated with placeholder/guessed
values, per the "fail safely / don't invent" principle. A future resource-
tracking integration can extend this function without needing to touch
callers -- they'd simply start receiving real values for currently-omitted
fields.
"""

from typing import Optional

from app.context.schemas import OperationalContext


def build_operational_context(
    audience: str = "disaster_manager",
    language: str = "en",
    requested_provider: Optional[str] = None,
    requested_model: Optional[str] = None,
) -> OperationalContext:
    return OperationalContext(
        audience=audience,
        language=language,
        requested_provider=requested_provider,
        requested_model=requested_model,
    )
