import json
from pathlib import Path
from typing import Any, Dict, List


ACTION_LIBRARY_PATH = Path("data/knowledge/action_library.json")

RISK_ORDER = {
    "no_alert": 0,
    "watch": 1,
    "warning": 2,
    "trigger": 3,
}


def safe_float(value, default=None):
    try:
        if value is None:
            return default
        return round(float(value), 4)
    except Exception:
        return default


def load_action_library() -> List[Dict[str, Any]]:
    """
    Load the local Action Knowledge Base.

    This file must exist:
    data/knowledge/action_library.json
    """

    if not ACTION_LIBRARY_PATH.exists():
        print(f"WARNING: Action library not found: {ACTION_LIBRARY_PATH}")
        return []

    try:
        library = json.loads(ACTION_LIBRARY_PATH.read_text(encoding="utf-8"))

        if not isinstance(library, list):
            print("WARNING: Action library must be a list of knowledge items.")
            return []

        return library

    except json.JSONDecodeError as error:
        print(f"WARNING: Could not parse action library JSON: {error}")
        return []


def score_entry(entry: Dict[str, Any], context: Dict[str, Any]) -> float:
    score = 0.0

    entry_hazard = entry.get("hazard", "")
    entry_risk_level = entry.get("risk_level", "")
    entry_audience = entry.get("audience", "")

    hazard = context.get("hazard", "")
    risk_level = context.get("risk_level", "")
    audience = context.get("audience", "")
    feedback_signal = context.get("feedback_signal", "")
    spi = safe_float(context.get("spi"), 0.0)
    rainfall_anomaly_pct = safe_float(context.get("rainfall_anomaly_pct"), 0.0)

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

    if feedback_signal in ["strong_ground_signal", "emerging_ground_signal"]:
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


def retrieve_guidance(
    context: Dict[str, Any],
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    library = load_action_library()

    scored_items = []

    for entry in library:
        score = score_entry(entry, context)

        if score > 0:
            item = dict(entry)
            item["retrieval_score"] = score
            scored_items.append(item)

    scored_items = sorted(
        scored_items,
        key=lambda item: item["retrieval_score"],
        reverse=True,
    )

    return scored_items[:top_k]


def deduplicate_actions(actions: List[str], max_actions: int = 7) -> List[str]:
    seen = set()
    clean_actions = []

    for action in actions:
        normalized = action.strip().lower()

        if not normalized:
            continue

        if normalized in seen:
            continue

        seen.add(normalized)
        clean_actions.append(action.strip())

        if len(clean_actions) >= max_actions:
            break

    return clean_actions


def build_context_from_row(
    row: Dict[str, Any],
    audience: str,
    feedback_summary: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "country": row.get("country", ""),
        "district": row.get("district", ""),
        "hazard": row.get("hazard", ""),
        "risk_level": row.get("risk_level", ""),
        "audience": audience,
        "risk_score": safe_float(row.get("risk_score")),
        "hazard_probability": safe_float(row.get("hazard_probability")),
        "exposure": safe_float(row.get("exposure")),
        "vulnerability": safe_float(row.get("vulnerability")),
        "confidence": safe_float(row.get("confidence")),
        "rainfall_anomaly_pct": safe_float(row.get("rainfall_anomaly_pct")),
        "rainfall_anomaly_mm": safe_float(row.get("rainfall_anomaly_mm")),
        "spi": safe_float(row.get("spi")),
        "feedback_signal": feedback_summary.get("feedback_signal", "no_ground_signal"),
        "community_reports": feedback_summary.get("total_reports", 0),
    }


def build_climate_sentence(context: Dict[str, Any]) -> str:
    hazard = context.get("hazard", "")
    district = context.get("district", "")
    spi = context.get("spi")
    rainfall_anomaly_pct = context.get("rainfall_anomaly_pct")

    if hazard == "drought":
        return (
            f"Climate evidence for {district} indicates rainfall deficit conditions "
            f"with rainfall anomaly of {rainfall_anomaly_pct}% and SPI-like score of {spi}."
        )

    if hazard == "heavy_rainfall":
        return (
            f"Climate evidence for {district} indicates above-normal rainfall conditions "
            f"with rainfall anomaly of {rainfall_anomaly_pct}% and SPI-like score of {spi}."
        )

    if hazard == "heat_stress":
        return (
            f"Climate evidence for {district} indicates heat-related risk that requires "
            f"public safety, water and livelihood preparedness messaging."
        )

    return (
        f"Climate evidence for {district} indicates watch-level conditions that require "
        f"continued monitoring."
    )


def build_role_sentence(context: Dict[str, Any]) -> str:
    audience = context.get("audience", "")
    district = context.get("district", "")
    hazard = context.get("hazard", "").replace("_", " ")
    risk_level = context.get("risk_level", "")

    if audience == "disaster_manager":
        return (
            f"For disaster risk managers, {district} should be treated as a {risk_level} "
            f"priority for {hazard}. The immediate focus should be coordination, verification "
            f"and activation readiness."
        )

    if audience == "ngo_planner":
        return (
            f"For NGO and anticipatory action planners, {district} requires targeted planning "
            f"for {hazard}, using the risk score, local reports and vulnerability information "
            f"to prioritize support."
        )

    if audience == "extension_officer":
        return (
            f"For extension officers, {district} requires practical field advisories for "
            f"farmers, pastoralists and local communities affected by {hazard}."
        )

    if audience == "community":
        return (
            f"For community members in {district}, the message should focus on simple, "
            f"actionable preparedness steps for {hazard}."
        )

    return (
        f"For {audience.replace('_', ' ')}, {district} should be monitored closely for "
        f"{hazard}."
    )


def build_feedback_sentence(context: Dict[str, Any]) -> str:
    feedback_signal = context.get("feedback_signal", "no_ground_signal")
    community_reports = context.get("community_reports", 0)

    if feedback_signal == "strong_ground_signal":
        return (
            f"Community feedback is strong, with {community_reports} report(s). "
            f"Local verification and rapid response planning should be prioritized."
        )

    if feedback_signal == "emerging_ground_signal":
        return (
            f"Community feedback is emerging, with {community_reports} report(s). "
            f"Local officers should verify whether field-level impacts are increasing."
        )

    if feedback_signal == "limited_ground_signal":
        return (
            f"Community feedback is limited, with {community_reports} report(s). "
            f"Additional local observations should be collected."
        )

    return (
        "No strong community ground signal is currently available. Local officers should "
        "continue collecting field observations."
    )


def build_rag_advisory(
    row: Dict[str, Any],
    audience: str,
    feedback_summary: Dict[str, Any],
) -> Dict[str, Any]:
    context = build_context_from_row(
        row=row,
        audience=audience,
        feedback_summary=feedback_summary,
    )

    retrieved_guidance = retrieve_guidance(context=context, top_k=3)

    collected_actions = []

    for item in retrieved_guidance:
        collected_actions.extend(item.get("actions", []))

    if not collected_actions:
        collected_actions = [
            "Review the forecast signal with local officers.",
            "Coordinate with relevant sector offices.",
            "Prepare early warning messages for exposed communities.",
            "Collect local observations to confirm whether impacts are emerging.",
        ]

    recommended_actions = deduplicate_actions(collected_actions, max_actions=7)

    knowledge_sources = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "sector": item.get("sector"),
            "source_title": item.get("source_title"),
            "source_note": item.get("source_note"),
            "retrieval_score": item.get("retrieval_score"),
        }
        for item in retrieved_guidance
    ]

    if retrieved_guidance:
        retrieval_summary = (
            f"Retrieved {len(retrieved_guidance)} knowledge item(s) from the local "
            f"Action Knowledge Base for hazard={context.get('hazard')}, "
            f"risk_level={context.get('risk_level')}, audience={audience}, "
            f"feedback_signal={context.get('feedback_signal')}. Climate inputs used: "
            f"rainfall_anomaly_pct={context.get('rainfall_anomaly_pct')}, "
            f"spi={context.get('spi')}."
        )
    else:
        retrieval_summary = (
            f"No matching knowledge item was found in the local Action Knowledge Base for "
            f"hazard={context.get('hazard')}, risk_level={context.get('risk_level')}, "
            f"audience={audience}. Generic fallback actions were used."
        )

    role_specific_advisory = " ".join(
        [
            build_role_sentence(context),
            build_climate_sentence(context),
            build_feedback_sentence(context),
        ]
    )

    return {
        "mode": "local_rag",
        "context": context,
        "retrieved_guidance": retrieved_guidance,
        "knowledge_sources": knowledge_sources,
        "retrieval_summary": retrieval_summary,
        "recommended_actions": recommended_actions,
        "role_specific_advisory": role_specific_advisory,
    }