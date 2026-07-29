"""Stage 2 of hybrid retrieval: keyword/rule-based scoring.

This is a deliberate PORT (not a shared import) of app.advisory.rag_engine's
score_entry/retrieve_guidance -- kept as an independent copy so the old
rule-based /api/advisory/{district} surface and this new context/decision
retrieval pipeline can evolve separately without one change silently
affecting the other.
"""

from typing import Any, Dict, List

RISK_ORDER = {
    "no_alert": 0,
    "watch": 1,
    "warning": 2,
    "trigger": 3,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return round(float(value), 4)
    except Exception:
        return default


def score_entry(entry: Dict[str, Any], query: Dict[str, Any]) -> float:
    """Same scoring formula as app.advisory.rag_engine.score_entry."""
    score = 0.0

    entry_hazard = entry.get("hazard", "")
    entry_risk_level = entry.get("risk_level", "")
    entry_audience = entry.get("audience", "")

    hazard = query.get("hazard", "")
    risk_level = query.get("risk_level", "")
    audience = query.get("audience", "")
    feedback_signal = query.get("feedback_signal", "")
    spi = _safe_float(query.get("spi"), 0.0)
    rainfall_anomaly_pct = _safe_float(query.get("rainfall_anomaly_pct"), 0.0)

    if entry_hazard == hazard:
        score += 8
    elif entry_hazard == "any":
        score += 1
    else:
        score -= 4

    if entry_risk_level == risk_level:
        score += 4
    elif entry_risk_level == "any":
        score += 1
    else:
        entry_rank = RISK_ORDER.get(entry_risk_level, -1)
        context_rank = RISK_ORDER.get(risk_level, -1)

        if entry_rank >= 0 and context_rank >= 0:
            distance = abs(entry_rank - context_rank)

            if distance == 1:
                score += 1.5
            elif entry_rank < context_rank:
                score += 0.5
            else:
                score -= 1

    if entry_audience == audience:
        score += 3
    elif entry_audience == "any":
        score += 1

    if feedback_signal in ("strong_ground_signal", "emerging_ground_signal"):
        combined_text = " ".join(entry.get("actions", []))
        combined_text += " " + entry.get("rationale", "")
        combined_text = combined_text.lower()

        if "community" in combined_text:
            score += 0.8
        if "verify" in combined_text:
            score += 0.8
        if "local" in combined_text:
            score += 0.6

    if hazard == "drought" and spi <= -1.0:
        score += 1
    if hazard == "drought" and rainfall_anomaly_pct <= -20:
        score += 1
    if hazard == "heavy_rainfall" and spi >= 1.0:
        score += 1
    if hazard == "heavy_rainfall" and rainfall_anomaly_pct >= 20:
        score += 1

    return round(score, 3)


def retrieve(
    query: Dict[str, Any],
    library: List[Dict[str, Any]],
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Same scored_items/sorted/top_k pattern as rag_engine.retrieve_guidance."""
    scored_items = []

    for entry in library:
        score = score_entry(entry, query)
        if score > 0:
            item = dict(entry)
            item["retrieval_score"] = score
            scored_items.append(item)

    scored_items.sort(key=lambda item: item["retrieval_score"], reverse=True)
    return scored_items[:top_k]
