import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from fastapi import APIRouter
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/ai", tags=["AI Map Interpretation"])


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"

# Provider values:
#   free_auto  -> NVIDIA -> Gemini -> Groq only when no screenshot -> OpenRouter -> OpenAI -> rule fallback
#   auto       -> alias of free_auto
#   nvidia     -> NVIDIA only
#   gemini     -> Gemini only
#   groq       -> Groq only; text/JSON only
#   openrouter -> OpenRouter only
#   openai     -> OpenAI only
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").strip().lower()

OPENAI_DEFAULT_MODEL = os.getenv("OPENAI_MAP_AI_MODEL", "gpt-5")
NVIDIA_DEFAULT_MODEL = os.getenv(
    "NVIDIA_AI_MODEL",
    "nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
)
GEMINI_DEFAULT_MODEL = os.getenv("GEMINI_AI_MODEL", "gemini-2.5-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
GROQ_DEFAULT_MODEL = os.getenv("GROQ_AI_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_DEFAULT_MODEL = os.getenv("OPENROUTER_AI_MODEL", "openrouter/free")

NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

AI_PROVIDER_OPTIONS = [
    {
        "value": "free_auto",
        "label": "Automatic free-provider chain",
        "description": "NVIDIA NIM → Gemini → Groq if screenshot is off → OpenRouter → OpenAI → rule-based fallback.",
        "supports_screenshot": True,
        "models": [
            {"value": "auto", "label": "Automatic model per provider chain"},
        ],
    },
    {
        "value": "nvidia",
        "label": "NVIDIA NIM",
        "description": "Best option for map screenshot + structured JSON summaries.",
        "supports_screenshot": True,
        "models": [
            {"value": "nvidia/llama-3.1-nemotron-nano-vl-8b-v1", "label": "NVIDIA Llama 3.1 Nemotron Nano VL 8B"},
            {"value": "meta/llama-3.2-11b-vision-instruct", "label": "Meta Llama 3.2 11B Vision Instruct"},
            {"value": "meta/llama-3.2-90b-vision-instruct", "label": "Meta Llama 3.2 90B Vision Instruct"},
            {"value": "custom", "label": "Custom NVIDIA NIM model ID"},
        ],
    },
    {
        "value": "gemini",
        "label": "Google Gemini",
        "description": "Good multimodal option for screenshot + text summaries.",
        "supports_screenshot": True,
        "models": [
            {"value": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
            {"value": "gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite"},
            {"value": "custom", "label": "Custom Gemini model ID"},
        ],
    },
    {
        "value": "groq",
        "label": "Groq",
        "description": "Fast text-only option. Use when the screenshot toggle is off.",
        "supports_screenshot": False,
        "models": [
            {"value": "openai/gpt-oss-120b", "label": "GPT-OSS 120B on Groq"},
            {"value": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B Versatile on Groq"},
            {"value": "custom", "label": "Custom Groq model ID"},
        ],
    },
    {
        "value": "openrouter",
        "label": "OpenRouter",
        "description": "Free-model router / fallback route.",
        "supports_screenshot": True,
        "models": [
            {"value": "openrouter/free", "label": "OpenRouter free model router"},
            {"value": "custom", "label": "Custom OpenRouter model ID"},
        ],
    },
    {
        "value": "openai",
        "label": "OpenAI",
        "description": "Paid fallback if API billing is available.",
        "supports_screenshot": True,
        "models": [
            {"value": "gpt-5", "label": "GPT-5"},
            {"value": "gpt-4.1", "label": "GPT-4.1"},
            {"value": "gpt-4o", "label": "GPT-4o"},
            {"value": "custom", "label": "Custom OpenAI model ID"},
        ],
    },
]

LANGUAGE_LABELS = {
    "en": "English",
    "am": "Amharic",
    "om": "Oromifa / Afaan Oromo",
    "ti": "Tigrinya",
    "so": "Somali",
}

MAP_LAYER_LABELS = {
    "hazard": "Hazard map",
    "risk_score": "Risk score map",
    "hazard_probability": "Hazard probability map",
    "exposure": "Exposure map",
    "vulnerability": "Vulnerability map",
}

CLIMATE_INDICATOR_LABELS = {
    "rainfall_total": "Rainfall Total",
    "spi": "Standardized Precipitation Index",
    "cdd": "Consecutive dry days",
    "cwd": "Consecutive wet days",
    "dryspell_prob_5d": "Dry spell probability ≥5 days",
    "dryspell_prob_7d": "Dry spell probability ≥7 days",
    "dryspell_prob_9d": "Dry spell probability ≥9 days",
    "rainfall_percentile": "Rainfall percentile",
    "rainfall_anomaly_pct": "Rainfall anomaly",
}


class ForecastSelection(BaseModel):
    forecastScale: Optional[str] = "subseasonal"
    lead: Optional[str] = "week_1"
    layer: Optional[str] = "risk_score"
    indicator: Optional[str] = "spi"
    activeMapGroup: Optional[str] = None
    activeMapLabel: Optional[str] = None
    seasonalScale: Optional[str] = None
    seasonalScaleLabel: Optional[str] = None
    seasonalIndicator: Optional[str] = None
    seasonalIndicatorLabel: Optional[str] = None
    seasonalPeriod: Optional[str] = None
    seasonalPeriodLabel: Optional[str] = None
    seasonalProduct: Optional[str] = None
    seasonalProductLabel: Optional[str] = None
    climateMapView: Optional[str] = None
    seasonalMap: Optional[Dict[str, Any]] = None
    seasonalCompareMaps: Optional[Dict[str, Any]] = None


class AdminSelection(BaseModel):
    regionId: Optional[str] = ""
    zoneId: Optional[str] = ""
    woredaId: Optional[str] = ""
    regionLabel: Optional[str] = ""
    zoneLabel: Optional[str] = ""
    woredaLabel: Optional[str] = ""
    boundaryLevel: Optional[str] = ""


class MapContext(BaseModel):
    metric_type: Optional[str] = ""
    seasonal_context: Optional[str] = ""
    hazard_type: Optional[str] = ""
    current_seasonal_context: Optional[str] = ""
    admin_scope: Optional[str] = ""
    active_map_group: Optional[str] = ""
    displayed_map: Optional[str] = ""
    seasonal_scale: Optional[str] = ""
    seasonal_scale_label: Optional[str] = ""
    seasonal_indicator: Optional[str] = ""
    seasonal_indicator_label: Optional[str] = ""
    seasonal_period: Optional[str] = ""
    seasonal_period_label: Optional[str] = ""
    seasonal_product: Optional[str] = ""
    seasonal_product_label: Optional[str] = ""
    climate_map_view: Optional[str] = ""
    seasonal_map_metadata: Optional[Dict[str, Any]] = None
    seasonal_compare_maps: Optional[Dict[str, Any]] = None


class AIMapInterpretationRequest(BaseModel):
    forecast_selection: ForecastSelection = Field(default_factory=ForecastSelection)
    admin_selection: AdminSelection = Field(default_factory=AdminSelection)
    map_context: MapContext = Field(default_factory=MapContext)

    top_admin_areas: List[Dict[str, Any]] = Field(default_factory=list)
    all_map_layer_summaries: Dict[str, Any] = Field(default_factory=dict)
    all_climate_indicator_summaries: Dict[str, Any] = Field(default_factory=dict)

    map_image_base64: Optional[str] = None
    use_screenshot: bool = False

    target_language: Optional[str] = "en"
    target_language_label: Optional[str] = "English"
    audience_focus: Optional[str] = (
        "farmers, rainfed agriculture, agro-pastoral communities, livestock, "
        "policymakers, DRM offices, and humanitarian organizations"
    )
    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None
    requested_model_label: Optional[str] = None


AI_MAP_REPORT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "target_language": {"type": "string"},
        "executive_summary": {"type": "string"},
        "national_spatial_overview": {"type": "array", "items": {"type": "string"}},
        "layer_by_layer_summary": {"type": "array", "items": {"type": "string"}},
        "indicator_by_indicator_summary": {"type": "array", "items": {"type": "string"}},
        "priority_area_justification": {"type": "array", "items": {"type": "string"}},
        "farmer_advisory": {"type": "array", "items": {"type": "string"}},
        "humanitarian_priorities": {"type": "array", "items": {"type": "string"}},
        "sms_summary": {"type": "string"},
    },
    "required": [
        "title",
        "target_language",
        "executive_summary",
        "national_spatial_overview",
        "layer_by_layer_summary",
        "indicator_by_indicator_summary",
        "priority_area_justification",
        "farmer_advisory",
        "humanitarian_priorities",
        "sms_summary",
    ],
}


class ProviderError(Exception):
    pass


def normalize_provider(value: str | None) -> str:
    provider = str(value or os.getenv("AI_PROVIDER", AI_PROVIDER) or "free_auto").strip().lower()
    aliases = {
        "auto": "free_auto",
        "multi": "free_auto",
        "multi_provider": "free_auto",
        "nvidia_nim": "nvidia",
        "google": "gemini",
        "google_gemini": "gemini",
        "open_router": "openrouter",
    }
    return aliases.get(provider, provider)


def clean_model_id(value: str | None) -> Optional[str]:
    text = str(value or "").strip()
    if not text or text.lower() in {"auto", "automatic", "default", "auto_default"}:
        return None
    return text


def resolve_model_for_provider(
    request: "AIMapInterpretationRequest",
    provider: str,
    default_model: str,
    env_name: Optional[str] = None,
    explicit_model: Optional[str] = None,
) -> str:
    if explicit_model:
        return explicit_model

    requested_provider = normalize_provider(request.requested_provider)
    requested_model = clean_model_id(request.requested_model)

    if requested_provider == provider and requested_model:
        return requested_model

    if env_name:
        return os.getenv(env_name, default_model)

    return default_model


def normalize_language_code(value: str | None) -> str:
    text = str(value or "en").strip().lower()
    if text in {"am", "amh", "amharic", "am-et", "አማርኛ"}:
        return "am"
    if text in {"om", "orm", "oromo", "oromifa", "afaan oromo", "afan oromo", "or"}:
        return "om"
    if text in {"ti", "tir", "tig", "tigrinya", "tigrigna", "ትግርኛ"}:
        return "ti"
    if text in {"so", "som", "somali", "af-soomaali", "af soomaali", "soomaali"}:
        return "so"
    if text in {"en", "eng", "english", "en-us", "en-gb"}:
        return "en"
    return text or "en"


def get_language_label(value: str | None) -> str:
    code = normalize_language_code(value)
    return LANGUAGE_LABELS.get(code, "English")


def get_language_instruction(value: str | None) -> str:
    code = normalize_language_code(value)
    if code == "am":
        return "Write the entire report in Amharic using Ethiopic script. Keep place names as provided when appropriate."
    if code == "om":
        return "Write the entire report in Oromifa / Afaan Oromo using Latin script. Keep place names as provided when appropriate."
    if code == "ti":
        return "Write the entire report in Tigrinya using Ethiopic script. Keep place names as provided when appropriate."
    if code == "so":
        return "Write the entire report in Somali using Latin script. Keep place names as provided when appropriate."
    return "Write the entire report in English. Keep place names as provided when appropriate."


def title_case(value: Any) -> str:
    if value is None:
        return "N/A"
    text = str(value).replace("_", " ").strip()
    if not text:
        return "N/A"
    return " ".join(word[:1].upper() + word[1:].lower() for word in text.split())


def get_map_group_label(forecast_selection: ForecastSelection) -> str:
    """Both the climate indicator maps section and the hazard/risk layers
    section are always visible together on the dashboard now (no tab
    switcher), so this always describes both rather than "whichever tab is
    active". The frontend normally sends activeMapGroup explicitly; this is
    only the fallback if that's missing.
    """
    if forecast_selection.activeMapGroup:
        return str(forecast_selection.activeMapGroup)

    return "Climate Indicator Maps and Hazard/Risk Layers"


def get_displayed_map_label(forecast_selection: ForecastSelection) -> str:
    if forecast_selection.activeMapLabel:
        return str(forecast_selection.activeMapLabel)

    indicator_label = CLIMATE_INDICATOR_LABELS.get(
        forecast_selection.seasonalIndicator or forecast_selection.indicator or "",
        title_case(forecast_selection.seasonalIndicator or forecast_selection.indicator or "spi"),
    )
    layer_label = MAP_LAYER_LABELS.get(
        forecast_selection.layer or "",
        title_case(forecast_selection.layer or "hazard"),
    )
    return f"{indicator_label} (climate indicator) and {layer_label} (hazard/risk)"


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
        if number != number:
            return default
        return number
    except Exception:
        return default


def format_number(value: Any, digits: int = 2) -> str:
    number = safe_float(value)
    if number is None:
        return "N/A"
    return f"{number:.{digits}f}"


def area_name(item: Dict[str, Any]) -> str:
    return item.get("area_name") or item.get("woreda") or item.get("zone") or item.get("region") or "Selected area"


def get_area_location(item: Dict[str, Any]) -> str:
    parts = []
    for key in ["woreda", "zone", "region"]:
        if item.get(key):
            parts.append(str(item.get(key)))
    return ", ".join(parts) if parts else area_name(item)


def get_map_image_data_url(request: AIMapInterpretationRequest) -> Optional[str]:
    if not request.use_screenshot or not request.map_image_base64:
        return None
    value = request.map_image_base64.strip()
    if value.startswith("data:image/"):
        return value
    return f"data:image/png;base64,{value}"


def data_url_to_bytes(data_url: str) -> Tuple[bytes, str]:
    if not data_url.startswith("data:"):
        return base64.b64decode(data_url), "image/png"
    header, encoded = data_url.split(",", 1)
    mime_match = re.match(r"data:([^;]+);base64", header)
    mime_type = mime_match.group(1) if mime_match else "image/png"
    return base64.b64decode(encoded), mime_type


def parse_json_from_text(text: str) -> Dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def compact_json(value: Any, max_chars: int = 18000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...TRUNCATED..."


def read_knowledge_base_documents() -> List[Dict[str, str]]:
    if not KNOWLEDGE_BASE_DIR.exists():
        return []
    documents: List[Dict[str, str]] = []
    for path in sorted(KNOWLEDGE_BASE_DIR.glob("*.md")):
        try:
            documents.append(
                {
                    "title": path.stem.replace("_", " ").title(),
                    "path": str(path.relative_to(PROJECT_ROOT)),
                    "text": path.read_text(encoding="utf-8"),
                }
            )
        except Exception:
            continue
    return documents


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def retrieve_guidance(request: AIMapInterpretationRequest, limit: int = 5) -> List[Dict[str, str]]:
    documents = read_knowledge_base_documents()
    if not documents:
        return []

    query_parts = [
        request.forecast_selection.layer,
        request.forecast_selection.indicator,
        request.map_context.hazard_type,
        request.map_context.metric_type,
        request.map_context.seasonal_context,
        request.audience_focus,
        request.target_language_label,
        compact_json(request.all_map_layer_summaries, max_chars=3000),
        compact_json(request.all_climate_indicator_summaries, max_chars=3000),
    ]
    for item in request.top_admin_areas[:8]:
        query_parts.extend(
            [
                item.get("hazard"),
                item.get("risk_level"),
                item.get("region"),
                item.get("zone"),
                item.get("woreda"),
            ]
        )

    query_tokens = set(tokenize(" ".join(str(part) for part in query_parts if part)))
    scored = []
    for document in documents:
        doc_text = document["title"] + "\n" + document["text"]
        doc_tokens = set(tokenize(doc_text))
        overlap = len(query_tokens.intersection(doc_tokens))
        bonus = 0
        lowered = doc_text.lower()
        for keyword in [
            "drought",
            "dry",
            "flood",
            "wet",
            "livestock",
            "agriculture",
            "humanitarian",
            "sms",
            "water",
            "policy",
            "pasture",
        ]:
            if keyword in query_tokens and keyword in lowered:
                bonus += 3
        scored.append((overlap + bonus, document))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = []
    for score, document in scored[:limit]:
        if score <= 0 and selected:
            continue
        text = document["text"].strip()
        if len(text) > 2400:
            text = text[:2400] + "\n..."
        selected.append({"title": document["title"], "path": document["path"], "text": text})
    return selected


def build_system_prompt() -> str:
    return """
You are an expert climate risk, agriculture, livestock, agro-pastoralism, and humanitarian early-warning analyst.

Your job is to interpret Ethiopia-wide forecast map layers and climate indicator maps for Forecast2Action AI.

Important rules:
- Use structured JSON map summaries as the source of truth.
- Use the optional map screenshot only as supporting visual context.
- First explain the Ethiopia-wide spatial distribution, hotspots, low-value areas, high-value areas, and national patterns.
- Interpret all hazard/risk layers: hazard, risk score, hazard probability, exposure, and vulnerability.
- Interpret all seasonal climate indicators available in the payload: Rainfall Total, SPI, CDD, CWD, dry spell probability ≥5/7/9 days, and Rainfall Percentile.
- Then explain why the listed priority intervention areas were selected.
- Do not invent regions, zones, or woredas that are not present in the structured data.
- Provide farmer/agro-pastoral advisory and humanitarian priorities.
- Return only valid JSON matching the requested keys.
""".strip()


def build_user_prompt(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]]) -> str:
    language_label = get_language_label(request.target_language)
    language_instruction = get_language_instruction(request.target_language)

    forecast_window = title_case(request.forecast_selection.forecastScale)
    lead = title_case(request.forecast_selection.lead)
    admin_scope = request.map_context.admin_scope or "Ethiopia"
    active_layer = MAP_LAYER_LABELS.get(
        request.forecast_selection.layer or "",
        title_case(request.forecast_selection.layer or "hazard"),
    )
    active_indicator = (
        request.forecast_selection.seasonalIndicatorLabel
        or request.map_context.seasonal_indicator_label
        or CLIMATE_INDICATOR_LABELS.get(
            request.forecast_selection.seasonalIndicator or request.forecast_selection.indicator or "",
            title_case(request.forecast_selection.seasonalIndicator or request.forecast_selection.indicator or "spi"),
        )
    )
    active_map_group = request.map_context.active_map_group or get_map_group_label(request.forecast_selection)
    displayed_map = request.map_context.displayed_map or get_displayed_map_label(request.forecast_selection)
    seasonal_scale = request.forecast_selection.seasonalScaleLabel or request.map_context.seasonal_scale_label or title_case(request.forecast_selection.seasonalScale or request.map_context.seasonal_scale or "seasonal")
    seasonal_period = request.forecast_selection.seasonalPeriodLabel or request.map_context.seasonal_period_label or request.forecast_selection.seasonalPeriod or request.map_context.seasonal_period or lead
    seasonal_product = request.forecast_selection.seasonalProductLabel or request.map_context.seasonal_product_label or request.forecast_selection.seasonalProduct or request.map_context.seasonal_product or "N/A"
    climate_map_view = request.forecast_selection.climateMapView or request.map_context.climate_map_view or "single"
    selected_seasonal_map = request.forecast_selection.seasonalMap or request.map_context.seasonal_map_metadata

    payload = request.model_dump(exclude={"map_image_base64"})

    return f"""
OUTPUT LANGUAGE:
{language_instruction}

EXECUTIVE SUMMARY REQUIREMENT:
The executive_summary must explicitly mention:
- Forecast window: {forecast_window}
- Lead / horizon: {lead}
- Admin scope: {admin_scope}
- Active map group: {active_map_group}
- Displayed map: {displayed_map}
- Active map layer: {active_layer}
- Active climate indicator: {active_indicator}
- Climate indicator scale: {seasonal_scale}
- Seasonal period: {seasonal_period}
- Map product: {seasonal_product}
- Climate map view: {climate_map_view}
- Output language: {language_label}

PRIMARY INTERPRETATION FOCUS:
The dashboard always shows two sections together, not a switchable tab: the Climate Indicator Maps section (displaying {active_indicator}, {seasonal_scale} scale, {seasonal_period} period, {seasonal_product} product) and the Hazard/Risk Layers section (displaying {active_layer}). Interpret both sections in this report.
Use the seasonal map metadata, selected scale, period, product, and comparison maps to explain Forecast vs Historical Climatology vs Anomaly for the climate indicator section.
This report must be country-level first. Focus on spatial distribution across Ethiopia:
- where hotspots are found
- where high values and low values are found
- overall Ethiopia-wide pattern
- layer-by-layer interpretation of Hazard / Risk Score / Hazard Probability / Exposure / Vulnerability
- indicator-by-indicator interpretation of Rainfall Total / SPI / CDD / CWD / dryspell_prob_5d / dryspell_prob_7d / dryspell_prob_9d / Rainfall Percentile

Only after the country-level interpretation, explain why the Priority Intervention Areas and Action Queue areas were selected.

SELECTED SEASONAL MAP METADATA:
{compact_json(selected_seasonal_map, max_chars=6000)}

TASK:
1. Provide national_spatial_overview for Ethiopia-wide patterns.
2. Provide layer_by_layer_summary with one clear bullet for each map layer.
3. Provide indicator_by_indicator_summary with one clear bullet for each climate indicator.
4. Provide priority_area_justification explaining how the spatial patterns justify the selected priority areas.
5. Provide farmer_advisory for farmers and agro-pastoral communities.
6. Provide humanitarian_priorities for DRM and humanitarian resource allocation.
7. Provide a short sms_summary in the output language.

STRUCTURED MAP DATA:
{compact_json(payload, max_chars=28000)}

RETRIEVED EARLY-ACTION GUIDANCE:
{compact_json(retrieved_guidance, max_chars=9000)}

Return only JSON with these keys:
title, target_language, executive_summary, national_spatial_overview,
layer_by_layer_summary, indicator_by_indicator_summary,
priority_area_justification, farmer_advisory, humanitarian_priorities, sms_summary.
""".strip()


def validate_report_shape(report: Dict[str, Any]) -> Dict[str, Any]:
    required_array_keys = [
        "national_spatial_overview",
        "layer_by_layer_summary",
        "indicator_by_indicator_summary",
        "priority_area_justification",
        "farmer_advisory",
        "humanitarian_priorities",
    ]
    for key in required_array_keys:
        if key not in report or not isinstance(report[key], list):
            report[key] = [] if key not in report else [str(report[key])]
    for key in ["title", "target_language", "executive_summary", "sms_summary"]:
        if key not in report or report[key] is None:
            report[key] = ""
    return report


def fallback_report(
    request: AIMapInterpretationRequest,
    retrieved_guidance: List[Dict[str, str]],
    error_message: Optional[str] = None,
    provider_errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    language_code = normalize_language_code(request.target_language)
    language_label = get_language_label(language_code)
    forecast_window = title_case(request.forecast_selection.forecastScale)
    lead = title_case(request.forecast_selection.lead)
    admin_scope = request.map_context.admin_scope or "Ethiopia"
    active_layer = MAP_LAYER_LABELS.get(request.forecast_selection.layer or "", title_case(request.forecast_selection.layer or "hazard"))
    active_indicator = (
        request.forecast_selection.seasonalIndicatorLabel
        or request.map_context.seasonal_indicator_label
        or CLIMATE_INDICATOR_LABELS.get(request.forecast_selection.seasonalIndicator or request.forecast_selection.indicator or "", title_case(request.forecast_selection.seasonalIndicator or request.forecast_selection.indicator or "spi"))
    )
    active_map_group = request.map_context.active_map_group or get_map_group_label(request.forecast_selection)
    displayed_map = request.map_context.displayed_map or get_displayed_map_label(request.forecast_selection)
    seasonal_period = request.forecast_selection.seasonalPeriodLabel or request.map_context.seasonal_period_label or request.forecast_selection.seasonalPeriod or request.map_context.seasonal_period or lead
    seasonal_product = request.forecast_selection.seasonalProductLabel or request.map_context.seasonal_product_label or request.forecast_selection.seasonalProduct or request.map_context.seasonal_product or "N/A"

    top_areas = request.top_admin_areas[:5] if request.top_admin_areas else []
    if top_areas:
        priority_text = [
            (
                f"{get_area_location(item)} is selected because it ranks high in the priority queue. "
                f"Risk score: {format_number(item.get('risk_score'))}; "
                f"hazard probability: {format_number(item.get('hazard_probability'))}; "
                f"exposure: {format_number(item.get('exposure'))}; "
                f"vulnerability: {format_number(item.get('vulnerability'))}."
            )
            for item in top_areas
        ]
    else:
        priority_text = ["No priority-area ranking was provided for justification."]

    layer_summary = []
    for key, label in MAP_LAYER_LABELS.items():
        summary = request.all_map_layer_summaries.get(key)
        if summary:
            layer_summary.append(
                f"{label}: national summary was provided. Review hotspot areas, low-value areas, and regional statistics to interpret the country-level pattern."
            )
        else:
            layer_summary.append(f"{label}: no national summary was provided.")

    indicator_summary = []
    for key, label in CLIMATE_INDICATOR_LABELS.items():
        summary = request.all_climate_indicator_summaries.get(key)
        if summary:
            indicator_summary.append(
                f"{label}: national summary was provided. Review the highest/lowest areas and regional statistics to understand the spatial pattern."
            )
        else:
            indicator_summary.append(f"{label}: no national summary was provided.")

    return {
        "title": "AI Map Interpretation & Advisory",
        "target_language": language_label,
        "executive_summary": (
            f"Forecast window: {forecast_window}; Lead / horizon: {lead}; Admin scope: {admin_scope}; "
            f"Active map group: {active_map_group}; Displayed map: {displayed_map}; "
            f"Active map layer: {active_layer}; Active climate indicator: {active_indicator}; "
            f"Seasonal period: {seasonal_period}; Map product: {seasonal_product}; "
            f"Output language: {language_label}. The report is using the rule-based fallback because no configured AI provider completed successfully."
        ),
        "national_spatial_overview": [
            "The Ethiopia-wide interpretation should use all hazard/risk layers and all climate indicators, not only the priority intervention list.",
            "Hotspots should be identified from high-value areas and hotspot regions in the all-layer summaries; lower-value areas should be used as contrast areas.",
        ],
        "layer_by_layer_summary": layer_summary,
        "indicator_by_indicator_summary": indicator_summary,
        "priority_area_justification": priority_text,
        "farmer_advisory": [
            "Conserve available water and strengthen household or farm-level water storage.",
            "Adjust planting and field activities according to rainfall onset, dry-spell risk, or wet-spell risk.",
            "Monitor pasture, crop stress, livestock body condition, and local water availability.",
            "Report emerging impacts to local extension, DRM, or community focal points.",
        ],
        "humanitarian_priorities": [
            "Prioritize resource allocation where hazard probability, exposure, and vulnerability overlap.",
            "Use community ground-truth reports to confirm whether forecast risk is becoming observed impact.",
            "Coordinate DRM, agriculture, livestock, water, and humanitarian actors around the highest-risk hotspots.",
        ],
        "sms_summary": (
            f"EARLY WARNING: {admin_scope}. {forecast_window} {lead} forecast. "
            f"Monitor local climate conditions and follow guidance from local authorities."
        ),
        "_metadata": {
            "ai_engine": "rule_based_fallback",
            "provider": None,
            "model": None,
            "requested_provider": normalize_provider(request.requested_provider),
            "requested_model": clean_model_id(request.requested_model) or "auto",
            "used_screenshot": bool(get_map_image_data_url(request)),
            "target_language": language_label,
            "target_language_code": language_code,
            "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
            "error": error_message,
            "provider_errors": provider_errors or [],
        },
    }


def build_chat_messages(
    request: AIMapInterpretationRequest,
    retrieved_guidance: List[Dict[str, str]],
    include_image: bool,
) -> Tuple[List[Dict[str, Any]], bool]:
    system_prompt = build_system_prompt() + "\nReturn only valid JSON with exactly the requested keys. No Markdown fences."
    user_prompt = build_user_prompt(request, retrieved_guidance)
    image_url = get_map_image_data_url(request) if include_image else None

    content: Any
    if image_url:
        content = [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
    else:
        content = user_prompt

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ], bool(image_url)


def call_chat_completions_provider(
    *,
    provider_name: str,
    api_key_env: str,
    base_url: str,
    model: str,
    request: AIMapInterpretationRequest,
    retrieved_guidance: List[Dict[str, str]],
    include_image: bool,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise ProviderError(f"{api_key_env} is not set.")

    try:
        from openai import OpenAI
    except Exception as exc:
        raise ProviderError("OpenAI Python package is required. Run: pip install openai") from exc

    messages, used_image = build_chat_messages(request, retrieved_guidance, include_image=include_image)
    client = OpenAI(base_url=base_url, api_key=api_key)

    kwargs: Dict[str, Any] = {}
    if extra_headers:
        kwargs["extra_headers"] = extra_headers

    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=float(os.getenv("AI_TEMPERATURE", "0.2")),
        top_p=float(os.getenv("AI_TOP_P", "0.7")),
        max_tokens=int(os.getenv("AI_MAX_TOKENS", "2800")),
        **kwargs,
    )

    text = completion.choices[0].message.content or ""
    report = validate_report_shape(parse_json_from_text(text))
    report["_metadata"] = {
        "ai_engine": f"{provider_name}_chat_completions",
        "provider": provider_name,
        "model": model,
        "requested_provider": normalize_provider(request.requested_provider),
        "requested_model": clean_model_id(request.requested_model) or "auto",
        "base_url": base_url,
        "used_screenshot": used_image,
        "target_language": get_language_label(request.target_language),
        "target_language_code": normalize_language_code(request.target_language),
        "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
    }
    return report


def call_nvidia_nim_model(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]]) -> Dict[str, Any]:
    return call_chat_completions_provider(
        provider_name="nvidia_nim",
        api_key_env="NVIDIA_API_KEY",
        base_url=os.getenv("NVIDIA_BASE_URL", NVIDIA_BASE_URL),
        model=resolve_model_for_provider(request, "nvidia", NVIDIA_DEFAULT_MODEL, "NVIDIA_AI_MODEL"),
        request=request,
        retrieved_guidance=retrieved_guidance,
        include_image=True,
    )


def call_groq_model(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]], model: Optional[str] = None) -> Dict[str, Any]:
    return call_chat_completions_provider(
        provider_name="groq",
        api_key_env="GROQ_API_KEY",
        base_url=os.getenv("GROQ_BASE_URL", GROQ_BASE_URL),
        model=model or resolve_model_for_provider(request, "groq", GROQ_DEFAULT_MODEL, "GROQ_AI_MODEL"),
        request=request,
        retrieved_guidance=retrieved_guidance,
        include_image=False,
    )


def call_openrouter_model(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]]) -> Dict[str, Any]:
    site_url = os.getenv("OPENROUTER_SITE_URL", "https://forecast2action-ai.vercel.app")
    app_title = os.getenv("OPENROUTER_APP_TITLE", "Forecast2Action AI")
    return call_chat_completions_provider(
        provider_name="openrouter",
        api_key_env="OPENROUTER_API_KEY",
        base_url=os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
        model=resolve_model_for_provider(request, "openrouter", OPENROUTER_DEFAULT_MODEL, "OPENROUTER_AI_MODEL"),
        request=request,
        retrieved_guidance=retrieved_guidance,
        include_image=bool(get_map_image_data_url(request)),
        extra_headers={"HTTP-Referer": site_url, "X-OpenRouter-Title": app_title},
    )


def call_gemini_model(
    request: AIMapInterpretationRequest,
    retrieved_guidance: List[Dict[str, str]],
    model: Optional[str] = None,
) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ProviderError("GEMINI_API_KEY or GOOGLE_API_KEY is not set.")

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise ProviderError("Google Gen AI package is required. Run: pip install google-genai") from exc

    gemini_model = model or resolve_model_for_provider(request, "gemini", GEMINI_DEFAULT_MODEL, "GEMINI_AI_MODEL")
    client = genai.Client(api_key=api_key)
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(request, retrieved_guidance)
    text_prompt = f"{system_prompt}\n\n{user_prompt}\n\nReturn only valid JSON. No Markdown fences."

    contents: List[Any] = [types.Part.from_text(text_prompt)]
    image_url = get_map_image_data_url(request)
    used_image = False
    if image_url:
        image_bytes, mime_type = data_url_to_bytes(image_url)
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
        used_image = True

    try:
        response = client.models.generate_content(
            model=gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=float(os.getenv("AI_TEMPERATURE", "0.2")),
                top_p=float(os.getenv("AI_TOP_P", "0.7")),
                max_output_tokens=int(os.getenv("AI_MAX_TOKENS", "2800")),
            ),
        )
    except TypeError:
        # Older SDK versions may prefer plain dictionaries for config.
        response = client.models.generate_content(
            model=gemini_model,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "temperature": float(os.getenv("AI_TEMPERATURE", "0.2")),
                "top_p": float(os.getenv("AI_TOP_P", "0.7")),
                "max_output_tokens": int(os.getenv("AI_MAX_TOKENS", "2800")),
            },
        )

    report = validate_report_shape(parse_json_from_text(response.text or ""))
    report["_metadata"] = {
        "ai_engine": "gemini_generate_content",
        "provider": "gemini",
        "model": gemini_model,
        "requested_provider": normalize_provider(request.requested_provider),
        "requested_model": clean_model_id(request.requested_model) or "auto",
        "used_screenshot": used_image,
        "target_language": get_language_label(request.target_language),
        "target_language_code": normalize_language_code(request.target_language),
        "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
    }
    return report


def call_openai_model(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]]) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ProviderError("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except Exception as exc:
        raise ProviderError("OpenAI Python package is required. Run: pip install openai") from exc

    client = OpenAI(api_key=api_key)
    model = resolve_model_for_provider(request, "openai", OPENAI_DEFAULT_MODEL, "OPENAI_MAP_AI_MODEL")
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(request, retrieved_guidance)
    image_url = get_map_image_data_url(request)

    content: List[Dict[str, Any]] = [{"type": "input_text", "text": user_prompt}]
    if image_url:
        content.append({"type": "input_image", "image_url": image_url, "detail": "low"})

    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": content},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ai_map_interpretation_report",
                    "strict": True,
                    "schema": AI_MAP_REPORT_SCHEMA,
                }
            },
            max_output_tokens=int(os.getenv("AI_MAX_TOKENS", "2800")),
        )
        report = validate_report_shape(parse_json_from_text(response.output_text))
        engine = "openai_responses_api"
    except Exception as structured_error:
        fallback_content: List[Dict[str, Any]] = [
            {
                "type": "input_text",
                "text": f"{system_prompt}\n\n{user_prompt}\n\nReturn only valid JSON. Do not include Markdown fences.",
            }
        ]
        if image_url:
            fallback_content.append({"type": "input_image", "image_url": image_url, "detail": "low"})
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": fallback_content}],
            max_output_tokens=int(os.getenv("AI_MAX_TOKENS", "2800")),
        )
        report = validate_report_shape(parse_json_from_text(response.output_text))
        engine = "openai_responses_api_json_fallback"
        report.setdefault("_metadata", {})["structured_output_error"] = str(structured_error)

    report["_metadata"] = {
        **report.get("_metadata", {}),
        "ai_engine": engine,
        "provider": "openai",
        "model": model,
        "requested_provider": normalize_provider(request.requested_provider),
        "requested_model": clean_model_id(request.requested_model) or "auto",
        "used_screenshot": bool(image_url),
        "target_language": get_language_label(request.target_language),
        "target_language_code": normalize_language_code(request.target_language),
        "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
    }
    return report


def try_provider(provider_label: str, func, errors: List[str]) -> Optional[Dict[str, Any]]:
    try:
        return func()
    except Exception as exc:
        errors.append(f"{provider_label} failed: {exc}")
        return None


def call_configured_ai_provider(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]]) -> Dict[str, Any]:
    provider = normalize_provider(request.requested_provider or os.getenv("AI_PROVIDER", AI_PROVIDER))

    if provider in {"auto", "free_auto", "multi", "multi_provider"}:
        errors: List[str] = []

        # 1. NVIDIA NIM vision model first.
        if os.getenv("NVIDIA_API_KEY"):
            result = try_provider("NVIDIA NIM", lambda: call_nvidia_nim_model(request, retrieved_guidance), errors)
            if result:
                result.setdefault("_metadata", {})["provider_chain"] = "free_auto"
                result["_metadata"]["provider_attempts"] = ["nvidia"]
                result["_metadata"]["provider_errors"] = errors
                return result
        else:
            errors.append("NVIDIA skipped: NVIDIA_API_KEY is not set.")

        # 2. Gemini Flash / Flash-Lite second.
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            for gemini_model in [os.getenv("GEMINI_AI_MODEL", GEMINI_DEFAULT_MODEL), os.getenv("GEMINI_FALLBACK_MODEL", GEMINI_FALLBACK_MODEL)]:
                if not gemini_model:
                    continue
                result = try_provider(
                    f"Gemini {gemini_model}",
                    lambda m=gemini_model: call_gemini_model(request, retrieved_guidance, model=m),
                    errors,
                )
                if result:
                    result.setdefault("_metadata", {})["provider_chain"] = "free_auto"
                    result["_metadata"]["provider_attempts"] = ["nvidia", "gemini"]
                    result["_metadata"]["provider_errors"] = errors
                    return result
        else:
            errors.append("Gemini skipped: GEMINI_API_KEY/GOOGLE_API_KEY is not set.")

        # 3. Groq only when screenshot is disabled or absent.
        screenshot_is_active = bool(get_map_image_data_url(request))
        if not screenshot_is_active:
            if os.getenv("GROQ_API_KEY"):
                groq_models = [os.getenv("GROQ_AI_MODEL", GROQ_DEFAULT_MODEL), os.getenv("GROQ_FALLBACK_MODEL", GROQ_FALLBACK_MODEL)]
                for groq_model in groq_models:
                    if not groq_model:
                        continue
                    result = try_provider(
                        f"Groq {groq_model}",
                        lambda m=groq_model: call_groq_model(request, retrieved_guidance, model=m),
                        errors,
                    )
                    if result:
                        result.setdefault("_metadata", {})["provider_chain"] = "free_auto"
                        result["_metadata"]["provider_attempts"] = ["nvidia", "gemini", "groq"]
                        result["_metadata"]["provider_errors"] = errors
                        return result
            else:
                errors.append("Groq skipped: GROQ_API_KEY is not set.")
        else:
            errors.append("Groq skipped: screenshot is enabled, and Groq is configured here as text-only.")

        # 4. OpenRouter free.
        if os.getenv("OPENROUTER_API_KEY"):
            result = try_provider("OpenRouter free", lambda: call_openrouter_model(request, retrieved_guidance), errors)
            if result:
                result.setdefault("_metadata", {})["provider_chain"] = "free_auto"
                result["_metadata"]["provider_attempts"] = ["nvidia", "gemini", "groq", "openrouter"]
                result["_metadata"]["provider_errors"] = errors
                return result
        else:
            errors.append("OpenRouter skipped: OPENROUTER_API_KEY is not set.")

        # 5. OpenAI if billing is available/configured.
        if os.getenv("OPENAI_API_KEY"):
            result = try_provider("OpenAI", lambda: call_openai_model(request, retrieved_guidance), errors)
            if result:
                result.setdefault("_metadata", {})["provider_chain"] = "free_auto"
                result["_metadata"]["provider_attempts"] = ["nvidia", "gemini", "groq", "openrouter", "openai"]
                result["_metadata"]["provider_errors"] = errors
                return result
        else:
            errors.append("OpenAI skipped: OPENAI_API_KEY is not set.")

        raise ProviderError(" | ".join(errors) if errors else "No provider completed successfully.")

    if provider == "nvidia":
        return call_nvidia_nim_model(request, retrieved_guidance)
    if provider == "gemini":
        return call_gemini_model(request, retrieved_guidance)
    if provider == "groq":
        if get_map_image_data_url(request):
            raise ProviderError("Groq provider is configured as text-only. Disable screenshot or use NVIDIA/Gemini/OpenRouter/OpenAI.")
        return call_groq_model(request, retrieved_guidance)
    if provider == "openrouter":
        return call_openrouter_model(request, retrieved_guidance)
    if provider == "openai":
        return call_openai_model(request, retrieved_guidance)

    raise ProviderError(f"Unsupported AI_PROVIDER='{provider}'. Use free_auto, openai, nvidia, gemini, groq, or openrouter.")


@router.get("/model-options")
async def get_ai_model_options() -> Dict[str, Any]:
    return {
        "default_provider": normalize_provider(os.getenv("AI_PROVIDER", AI_PROVIDER)),
        "providers": AI_PROVIDER_OPTIONS,
        "configured": {
            "nvidia": bool(os.getenv("NVIDIA_API_KEY")),
            "gemini": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
            "groq": bool(os.getenv("GROQ_API_KEY")),
            "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
            "openai": bool(os.getenv("OPENAI_API_KEY")),
        },
        "environment_defaults": {
            "nvidia": os.getenv("NVIDIA_AI_MODEL", NVIDIA_DEFAULT_MODEL),
            "gemini": os.getenv("GEMINI_AI_MODEL", GEMINI_DEFAULT_MODEL),
            "gemini_fallback": os.getenv("GEMINI_FALLBACK_MODEL", GEMINI_FALLBACK_MODEL),
            "groq": os.getenv("GROQ_AI_MODEL", GROQ_DEFAULT_MODEL),
            "groq_fallback": os.getenv("GROQ_FALLBACK_MODEL", GROQ_FALLBACK_MODEL),
            "openrouter": os.getenv("OPENROUTER_AI_MODEL", OPENROUTER_DEFAULT_MODEL),
            "openai": os.getenv("OPENAI_MAP_AI_MODEL", OPENAI_DEFAULT_MODEL),
        },
    }


@router.get("/provider-status")
async def get_ai_provider_status() -> Dict[str, Any]:
    provider = normalize_provider(os.getenv("AI_PROVIDER", AI_PROVIDER))
    return {
        "ai_provider": provider,
        "routing_order_when_free_auto": [
            "nvidia_nim_vision",
            "gemini_flash_or_flash_lite",
            "groq_text_only_when_screenshot_disabled",
            "openrouter_free",
            "openai_if_billing_available",
            "rule_based_fallback",
        ],
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "openai_model": os.getenv("OPENAI_MAP_AI_MODEL", OPENAI_DEFAULT_MODEL),
        "nvidia_configured": bool(os.getenv("NVIDIA_API_KEY")),
        "nvidia_model": os.getenv("NVIDIA_AI_MODEL", NVIDIA_DEFAULT_MODEL),
        "nvidia_base_url": os.getenv("NVIDIA_BASE_URL", NVIDIA_BASE_URL),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "gemini_model": os.getenv("GEMINI_AI_MODEL", GEMINI_DEFAULT_MODEL),
        "gemini_fallback_model": os.getenv("GEMINI_FALLBACK_MODEL", GEMINI_FALLBACK_MODEL),
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "groq_model": os.getenv("GROQ_AI_MODEL", GROQ_DEFAULT_MODEL),
        "groq_fallback_model": os.getenv("GROQ_FALLBACK_MODEL", GROQ_FALLBACK_MODEL),
        "groq_base_url": os.getenv("GROQ_BASE_URL", GROQ_BASE_URL),
        "openrouter_configured": bool(os.getenv("OPENROUTER_API_KEY")),
        "openrouter_model": os.getenv("OPENROUTER_AI_MODEL", OPENROUTER_DEFAULT_MODEL),
        "openrouter_base_url": os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
    }


@router.post("/map-interpretation")
async def generate_ai_map_interpretation(request: AIMapInterpretationRequest) -> Dict[str, Any]:
    retrieved_guidance = retrieve_guidance(request)
    try:
        return call_configured_ai_provider(request, retrieved_guidance)
    except Exception as error:
        provider_errors = []
        text = str(error)
        if " | " in text:
            provider_errors = text.split(" | ")
        return fallback_report(
            request=request,
            retrieved_guidance=retrieved_guidance,
            error_message=str(error),
            provider_errors=provider_errors,
        )
