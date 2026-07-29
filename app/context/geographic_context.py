"""GeographicContext is built as part of build_hazard_geo_impact_context
(app.context.forecast_context) -- all four context pieces (forecast,
geography, hazard evidence, impact) come from the exact same real ranking
item, so they're built together rather than with four separate raster/API
lookups. Re-exported here for discoverability and so callers can import
`from app.context.geographic_context import build_hazard_geo_impact_context`
if that reads more naturally at the call site.
"""

from app.context.forecast_context import build_hazard_geo_impact_context

__all__ = ["build_hazard_geo_impact_context"]
