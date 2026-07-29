"""ImpactContext is built as part of build_hazard_geo_impact_context
(app.context.forecast_context) -- see that module's docstring. Re-exported
here for discoverability.
"""

from app.context.forecast_context import build_hazard_geo_impact_context

__all__ = ["build_hazard_geo_impact_context"]
