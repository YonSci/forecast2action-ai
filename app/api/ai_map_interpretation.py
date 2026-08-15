import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from fastapi import APIRouter
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.context.schemas import DecisionContextEnvelope


router = APIRouter(prefix="/api/ai", tags=["AI Map Interpretation"])
logger = logging.getLogger(__name__)


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
GEMINI_DEFAULT_MODEL = os.getenv("GEMINI_AI_MODEL", "gemini-flash-lite-latest")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-flash-latest")
GROQ_DEFAULT_MODEL = os.getenv("GROQ_AI_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_DEFAULT_MODEL = os.getenv("OPENROUTER_AI_MODEL", "google/gemini-2.5-flash-lite")

NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Kept in sync with frontend/src/components/AIMapInterpretation.jsx's
# FALLBACK_AI_PROVIDER_OPTIONS -- that's the fallback shown before this
# endpoint's response arrives; this is what actually renders afterward
# (GET /api/ai/model-options, fetched into providerOptions state). Only
# providers/models confirmed via live testing to handle the full
# comprehensive map payload (32 images) are listed -- NVIDIA (only ever
# manages 1 image, its whole context is 16,384 tokens) and Groq (hard
# free-tier token-per-minute limit for this much text) were removed from
# both places, though their call_*_model functions/explicit-provider
# selection still work for direct/advanced use. "free_auto" (the automatic
# chain), "openai" (paid), and every "custom model ID" entry were also
# removed by explicit request -- the automatic chain's own logic in
# call_configured_ai_provider still exists (still reachable via
# requested_provider="free_auto" from a direct API call, or as the
# AI_PROVIDER env default) but is no longer offered as a UI choice.
AI_PROVIDER_OPTIONS = [
    {
        # Default: tries Gemini first, then automatically fails over to
        # OpenRouter/OpenAI (see call_configured_ai_provider_for_stage's
        # "auto"/"free_auto" branch) instead of surfacing a single Gemini
        # hiccup as a full rule-based-fallback report. "models" stays empty
        # (no fixed model to pick) -- the frontend's model dropdown already
        # falls back to a single "Automatic" entry when this is empty.
        "value": "free_auto",
        "label": "Automatic (recommended)",
        "description": "Tries Gemini first, then automatically fails over to OpenRouter and OpenAI if Gemini is unavailable -- the most resilient option.",
        "supports_screenshot": True,
        "models": [],
    },
    {
        "value": "gemini",
        "label": "Google Gemini",
        "description": "Fastest and most reliable with the full comprehensive map set (all 32 images). No automatic failover if Gemini itself is unavailable -- pick Automatic for resilience.",
        "supports_screenshot": True,
        "models": [
            {"value": "gemini-flash-lite-latest", "label": "Gemini Flash-Lite (latest, fastest)"},
            {"value": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite (1M context)"},
            {"value": "gemini-flash-latest", "label": "Gemini Flash (latest)"},
        ],
    },
    {
        "value": "openrouter",
        "label": "OpenRouter",
        "description": "All models below confirmed to handle the full comprehensive map set (all 32 images).",
        "supports_screenshot": True,
        "models": [
            {"value": "google/gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite (1M context)"},
            {"value": "openai/gpt-5.6-luna", "label": "GPT-5.6 Luna (vision, 1M context)"},
            {"value": "meta-llama/llama-4-scout", "label": "Llama 4 Scout (vision, 1.3M context)"},
            {"value": "openai/gpt-5.6-terra", "label": "GPT-5.6 Terra (vision, 1M context)"},
            {"value": "z-ai/glm-4.6v", "label": "GLM-4.6V (vision, 131K context)"},
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
    "rx1day": "Rx1day (Daily Rainfall)",
    "rx5day": "Rx5day (5-Day Rainfall)",
    "dryspell_prob_5d": "Dry spell probability ≥5 days",
    "dryspell_prob_7d": "Dry spell probability ≥7 days",
    "dryspell_prob_9d": "Dry spell probability ≥9 days",
    "rainfall_percentile": "Rainfall percentile",
    "rainfall_anomaly_pct": "Rainfall anomaly",
}

# The 7 climate indicators actually visible in the UI / summarized with real
# data -- matches app.context.spatial_summary.CLIMATE_INDICATORS and
# frontend/src/constants/climateIndicators.js's VISIBLE_CLIMATE_INDICATORS
# (dryspell_prob_5d/7d/9d were hidden once Rx1day/Rx5day replaced them --
# this vocabulary is duplicated in 4+ places by necessity of module
# boundaries; changing it requires updating all of them, not just this one).
# CLIMATE_INDICATOR_LABELS above stays a superset lookup table (label
# fallback for an active_indicator outside this visible set), but any code
# that ITERATES "all climate indicators" must use this list, not
# CLIMATE_INDICATOR_LABELS.keys().
VISIBLE_CLIMATE_INDICATORS = ["rainfall_total", "spi", "cdd", "cwd", "rx1day", "rx5day", "rainfall_percentile"]


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
    # Populated unconditionally by populate_comprehensive_map_data() for
    # EVERY report (not just context-driven ones) -- one base64 PNG per
    # Hazard/Risk layer + climate-indicator/product combo for the resolved
    # period, regardless of what's currently displayed on screen. Kept
    # separate from map_image_base64 (the single current-dashboard-view
    # screenshot, which still captures on-screen context like selected
    # boundaries/priority markers that these raw raster renders don't).
    map_images: List[Dict[str, str]] = Field(default_factory=list)

    target_language: Optional[str] = "en"
    target_language_label: Optional[str] = "English"
    audience_focus: Optional[str] = (
        "farmers, rainfed agriculture, agro-pastoral communities, livestock, "
        "policymakers, DRM offices, and humanitarian organizations"
    )
    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None
    requested_model_label: Optional[str] = None

    # Additive: when context_id is supplied, the endpoint fetches the stored
    # Decision Context Envelope and fills top_admin_areas/all_map_layer_
    # summaries/all_climate_indicator_summaries from it ONLY where this
    # request didn't already provide them, then runs response_validator on
    # the result. Old callers (no context_id) get zero behavior change.
    context_id: Optional[str] = None
    prompt_version: Optional[str] = None


# Step 7 items 6/7 -- farmer/agro-pastoral advisory and humanitarian
# priorities are structured by timescale/category instead of a flat bullet
# list, matching this project's established preference for real keys over
# labels embedded in prose (same reasoning as priority_area_justification's
# object shape, step 7 item 5). validate_stage_shape only coerces
# declared "array"/"string" properties -- an "object" property is passed
# through untouched, so no coercion-logic changes are needed for this.
#
# Each bullet is itself a real structured object, not a bare string --
# confirmed real gap this closes: a farmer_advisory bullet used to be
# free-form prose with no way to tell WHICH real area it applied to, WHAT
# real evidence justified it, or HOW confident that evidence was, making
# it impossible to render, filter, or validate programmatically. `area`
# ties every bullet back to a real priority area (never invented); this
# schema is declared strictly (OpenAI's structured-output path enforces
# it exactly, not just Gemini's looser JSON mode).
_ADVISORY_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "area": {"type": "array", "items": {"type": "string"}},
        "action": {"type": "string"},
        "trigger": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        # Named cross_indicator_confidence (not the old generic
        # "confidence") because that's the only real thing this value ever
        # measures -- see app.context.statistical_evidence._evaluate_area_
        # signal, which computes it from agreement_score + available real
        # criteria, not data completeness or forecast/ensemble skill.
        "cross_indicator_confidence": {"type": "string"},
    },
    "required": ["area", "action", "trigger", "evidence", "cross_indicator_confidence"],
    "additionalProperties": False,
}

_TIMESCALED_ADVISORY_SCHEMA = {
    "type": "object",
    "properties": {
        "immediate": {"type": "array", "items": _ADVISORY_ITEM_SCHEMA},
        "near_term": {"type": "array", "items": _ADVISORY_ITEM_SCHEMA},
        "preparedness": {"type": "array", "items": _ADVISORY_ITEM_SCHEMA},
    },
}

_HUMANITARIAN_PRIORITIES_SCHEMA = {
    "type": "object",
    "properties": {
        "monitoring": {"type": "array", "items": _ADVISORY_ITEM_SCHEMA},
        "preparedness": {"type": "array", "items": _ADVISORY_ITEM_SCHEMA},
        "pre_positioning": {"type": "array", "items": _ADVISORY_ITEM_SCHEMA},
        "immediate_action": {"type": "array", "items": _ADVISORY_ITEM_SCHEMA},
    },
}

# character_count is deliberately NOT requested from the model -- it's
# real, deterministic, and Python computes it exactly from the real
# message text after generation (see _finalize_sms_messages); asking an
# LLM to count characters is a needless source of a wrong number for
# something with one unambiguous right answer.
_SMS_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "area": {"type": "string"},
        "audience": {"type": "string"},
        "hazard": {"type": "string"},
        "valid_period": {"type": "string"},
        "cross_indicator_confidence": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["area", "audience", "hazard", "valid_period", "cross_indicator_confidence", "message"],
    "additionalProperties": False,
}


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
        # Object, not string -- rank/scores/supporting-indicators are
        # deterministic (see app.context.statistical_evidence.build_
        # priority_area_justifications), only differentiator/recommended_
        # intervention_type are LLM-authored narrative merged on top.
        "priority_area_justification": {"type": "array", "items": {"type": "object"}},
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

# v2 schema, used ONLY when request.prompt_version == "v2" (context-aware
# requests). Adds 5 new properties, all added to `required` too -- OpenAI's
# strict json_schema mode (see call_openai_model below) rejects a schema
# where additionalProperties=false but `required` doesn't list every
# property, so these can't be left "optional" the normal JSON-Schema way.
# AI_MAP_REPORT_SCHEMA itself (v1, the default) is left completely
# unchanged so old requests have zero regression risk.
# sms_summary (v1's single national string) is dropped entirely here, not
# just overridden -- the real field is sms_messages (array of real,
# per-actionable-area objects, see _SMS_ITEM_SCHEMA) and leaving the old
# key declared would default it to an unused "" stub on every real report
# (validate_stage_shape defaults an undeclared-but-required string
# property to "" -- see its own docstring) -- dead legacy cruft, not
# backward compatibility, since nothing (frontend included) reads it.
_V1_PROPERTIES_WITHOUT_SMS_SUMMARY = {
    key: value for key, value in AI_MAP_REPORT_SCHEMA["properties"].items() if key != "sms_summary"
}
_V1_REQUIRED_WITHOUT_SMS_SUMMARY = [key for key in AI_MAP_REPORT_SCHEMA["required"] if key != "sms_summary"]

AI_MAP_REPORT_SCHEMA_V2: Dict[str, Any] = {
    **AI_MAP_REPORT_SCHEMA,
    "properties": {
        **_V1_PROPERTIES_WITHOUT_SMS_SUMMARY,
        "structured_actions": {"type": "array", "items": {"type": "object"}},
        "uncertainty_note": {"type": "string"},
        "restricted_or_deferred_actions": {"type": "array", "items": {"type": "string"}},
        "approval_requirements": {"type": "array", "items": {"type": "string"}},
        "evidence_citations": {"type": "array", "items": {"type": "object"}},
        # Step 7 items 6/7 -- overrides AI_MAP_REPORT_SCHEMA's v1 array<string>
        # declarations for these 2 fields, and declares agro_pastoral_advisory
        # (absent from v1 entirely). Required so validate_report_shape (called
        # on the FINAL merged staged report) doesn't stringify the new
        # structured objects these fields now hold -- validate_stage_shape only
        # coerces properties declared "array"/"string"; declaring these as
        # "object" here means the final validation pass leaves them untouched.
        "farmer_advisory": _TIMESCALED_ADVISORY_SCHEMA,
        "agro_pastoral_advisory": _TIMESCALED_ADVISORY_SCHEMA,
        "humanitarian_priorities": _HUMANITARIAN_PRIORITIES_SCHEMA,
        # Real, per-area messages -- see STAGE3_SCHEMA's sms_messages comment.
        "sms_messages": {"type": "array", "items": _SMS_ITEM_SCHEMA},
        # Phase 3 #17 -- same reasoning as farmer_advisory above: overrides
        # v1's array<string> declaration so the final validation pass
        # leaves these real structured objects untouched instead of
        # stringifying them.
        "layer_by_layer_summary": {"type": "array", "items": {"type": "object"}},
        "indicator_by_indicator_summary": {"type": "array", "items": {"type": "object"}},
    },
    "required": [
        *_V1_REQUIRED_WITHOUT_SMS_SUMMARY,
        "structured_actions",
        "uncertainty_note",
        "restricted_or_deferred_actions",
        "approval_requirements",
        "evidence_citations",
        "agro_pastoral_advisory",
        "sms_messages",
    ],
}


# Step 6 -- staged workflow schemas. Each stage returns only its own
# narrow slice; app.api.report_stages merges all 3 into one dict shaped
# like AI_MAP_REPORT_SCHEMA_V2 before returning to the caller, so nothing
# downstream (frontend, response_validator, citation builder) needs to
# know the report was produced in 3 calls instead of 1.
STAGE1_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # Object, not string, as of Phase 3 #17 -- each entry is a real
        # structured summary (national_signal, national_mean, highest_areas,
        # lowest_areas, high_or_very_high_area_pct, interpretation, confidence; see
        # app.context.statistical_evidence.build_structured_layer_summaries/
        # build_structured_indicator_summaries), not a free-text bullet, so
        # the frontend/response_validator/downstream stages get a real,
        # machine-checkable shape instead of prose to re-parse.
        "layer_by_layer_summary": {"type": "array", "items": {"type": "object"}},
        "indicator_by_indicator_summary": {"type": "array", "items": {"type": "object"}},
        "data_quality_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["layer_by_layer_summary", "indicator_by_indicator_summary", "data_quality_notes"],
}

STAGE2_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "executive_summary": {"type": "string"},
        "national_spatial_overview": {"type": "array", "items": {"type": "string"}},
        "compound_hazard_interpretation": {"type": "array", "items": {"type": "string"}},
        # Narrative-only, keyed by justification_id -- the LLM echoes back
        # the id of each real priority-area object it was given and adds
        # ONLY differentiator/recommended_intervention_type. It never
        # restates the real numbers; app.api.report_stages merges this
        # narrative onto the deterministic object afterward.
        "priority_area_justification": {"type": "array", "items": {"type": "object"}},
    },
    "required": [
        "executive_summary",
        "national_spatial_overview",
        "compound_hazard_interpretation",
        "priority_area_justification",
    ],
}

STAGE3_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "farmer_advisory": _TIMESCALED_ADVISORY_SCHEMA,
        "agro_pastoral_advisory": _TIMESCALED_ADVISORY_SCHEMA,
        "humanitarian_priorities": _HUMANITARIAN_PRIORITIES_SCHEMA,
        # Real, per-area messages instead of one national sms_summary --
        # confirmed real gap: the strongest signals are highly localized,
        # so a single national message was necessarily either too vague to
        # act on or misleading for areas it didn't really apply to.
        "sms_messages": {"type": "array", "items": _SMS_ITEM_SCHEMA},
    },
    "required": ["farmer_advisory", "agro_pastoral_advisory", "humanitarian_priorities", "sms_messages"],
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


def get_all_image_urls(request: AIMapInterpretationRequest) -> List[Dict[str, str]]:
    """Every image to attach to the LLM call: the single current-dashboard-
    view screenshot (if enabled -- captures on-screen context like selected
    boundaries/priority markers a raw raster render doesn't), plus every
    comprehensive map render in request.map_images (populated by
    populate_comprehensive_map_data() for every report, see that function).
    """
    images: List[Dict[str, str]] = []
    current_view_url = get_map_image_data_url(request)
    if current_view_url:
        images.append({"map_id": "current_dashboard_view", "label": "Current dashboard view", "data_url": current_view_url})
    for image in request.map_images:
        if image.get("data_url"):
            images.append(image)
    return images


def build_verification_metadata(request: AIMapInterpretationRequest, actual_image_count: int) -> Dict[str, Any]:
    """Durable, per-response proof of what comprehensive map data was
    actually attached to THIS specific call -- directly answers "was this
    data really sent to the LLM", not just "did the code intend to send
    it". actual_image_count is the number ACTUALLY placed in the provider
    call's content (post per-provider max_images cap -- see NVIDIA_MAX_
    IMAGES/build_chat_messages), so images_included is sliced to match --
    otherwise this would misreport all ~32 candidate images as "included"
    even when a provider's cap dropped some of them.
    """
    included_map_ids = [image["map_id"] for image in get_all_image_urls(request)[:actual_image_count]]
    return {
        "image_count": actual_image_count,
        "images_included": included_map_ids,
        "layer_summaries_included": len(request.all_map_layer_summaries),
        "indicator_summaries_included": len(request.all_climate_indicator_summaries),
    }


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


def _is_off_topic_for_actionable_hazards(document: Dict[str, str], actionable_hazard_types: set) -> bool:
    """True when a document's TITLE (a strong, deliberate signal -- not
    just body-text keyword presence, which could false-positive on a
    multi-hazard document that only mentions the other hazard in passing)
    marks it as specific to one hazard type that isn't in the real
    actionable set for this report. Confirmed real bug this fixes: this
    project's knowledge base has exactly 5 real documents and retrieval's
    own default limit is 5 -- a soft scoring penalty has ZERO practical
    effect when every document already fits within the limit regardless of
    score, so a genuinely off-topic document (e.g. flood guidance when the
    real national wet signal is completely insignificant) must be
    EXCLUDED outright, not merely ranked lower.
    """
    title_lower = document["title"].lower()
    is_flood_specific = ("flood" in title_lower or "wet spell" in title_lower) and "drought" not in title_lower
    is_drought_specific = "drought" in title_lower and "flood" not in title_lower and "wet" not in title_lower
    if is_flood_specific and "wet" not in actionable_hazard_types:
        return True
    if is_drought_specific and "drought" not in actionable_hazard_types:
        return True
    return False


def retrieve_guidance(
    request: AIMapInterpretationRequest, evidence: Optional[Dict[str, Any]] = None, limit: int = 5,
) -> List[Dict[str, str]]:
    """Retrieves early-action guidance documents. `evidence` (the real,
    already-computed national evidence -- see app.context.statistical_
    evidence.build_national_region_evidence) is optional for backward
    compatibility, but when given, real actionability (action_status --
    see build_priority_area_justifications) excludes documents specific
    to a hazard type that isn't actually actionable this period (see
    _is_off_topic_for_actionable_hazards).

    Confirmed real bug, fixed: without this, the query was built entirely
    from dashboard UI state (request.forecast_selection.layer, map_
    context.hazard_type, top_admin_areas) -- whatever happened to be on
    screen -- not the real national signal. Flood/wet-hazard guidance
    could be retrieved and reach Stage 3 even when the real national wet
    signal was completely insignificant (every wet-ranked area not_
    actionable), nudging even a "lite" model toward unwarranted flood
    advice for a period with no real flood risk.
    """
    documents = read_knowledge_base_documents()
    if not documents:
        return []

    actionable_hazard_types: Optional[set] = None
    if evidence is not None:
        actionable_hazard_types = {
            item.get("hazard_type")
            for item in evidence.get("priority_area_justifications", [])
            if item.get("action_status") in ("action", "preparedness")
        }

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
        if actionable_hazard_types is not None and _is_off_topic_for_actionable_hazards(document, actionable_hazard_types):
            continue
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


def build_system_prompt(version: Optional[str] = None, stage: Optional[str] = None) -> str:
    """Thin wrapper over app.advisory.prompts.registry -- defaults to "v1"
    (the original, unchanged prompt text) so old callers with no
    prompt_version keep getting identical behavior. `stage` ("stage1"/
    "stage2"/"stage3", see app.api.report_stages) selects that stage's own
    role framing instead of the legacy, stage-agnostic one -- omitting it
    (every call site in this file does) preserves this module's own
    single-call behavior unchanged.
    """
    from app.advisory.prompts.registry import get_system_prompt

    return get_system_prompt(version or "v1", stage)


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
- indicator-by-indicator interpretation of Rainfall Total / SPI / CDD / CWD / Rx1day / Rx5day / Rainfall Percentile

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


def _coerce_to_display_text(item: Any) -> str:
    """Coerces one array item to a plain string for React to render as a
    list item's text content. Real LLM providers (confirmed via manual
    end-to-end testing with NVIDIA NIM, not the deterministic fallback)
    sometimes return a structured object (e.g. {"layer": ..., "summary":
    ...}) inside an array the schema declares as list[str], especially once
    the underlying map-layer/indicator summaries fed into the prompt became
    real, richly-structured data (see app.context.spatial_summary) rather
    than the old simpler summaries. React crashes outright trying to render
    a raw object as a child -- "Objects are not valid as a React child" --
    so every item must be reduced to a string here, not just the list
    itself validated as a list.
    """
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("summary", "description", "text", "value", "label"):
            if isinstance(item.get(key), str):
                return item[key]
        return "; ".join(f"{k}: {v}" for k, v in item.items())
    return str(item)


def validate_stage_shape(data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Schema-driven coercion: for each property `schema` declares, forces
    array-of-string properties to a list of display-text strings (via
    _coerce_to_display_text, since real providers sometimes return a
    structured object inside a list[str] field), leaves array-of-object
    properties (e.g. evidence_citations) as-is when already a list
    (defaulting to [] otherwise, never flattened to strings), and defaults
    missing/None string properties to "". Generalizes the old validate_
    report_shape (which hardcoded these exact field lists) so both the
    legacy single-call schema and the new per-stage schemas share one
    coercion path -- provably identical behavior to the old function when
    called with AI_MAP_REPORT_SCHEMA_V2, see validate_report_shape below.
    """
    result = dict(data)
    for key, prop_schema in schema.get("properties", {}).items():
        prop_type = prop_schema.get("type")
        if prop_type == "string":
            value = result.get(key)
            if value is None:
                result[key] = ""
            elif not isinstance(value, str):
                # Real providers sometimes return a structured object for a
                # plain string field -- confirmed live: Gemini returned
                # executive_summary as {"forecast_window": ..., "lead_
                # horizon": ..., "report_scope": ..., "valid_period": ...,
                # "output_language": ..., "summary": "..."} instead of one
                # flowing string, after the Stage 2 prompt asked it to
                # "explicitly mention" those exact facts -- the model
                # structured them as separate keys rather than prose. This
                # was ALREADY handled for array items (_coerce_to_display_
                # text, below) but never for scalar string fields, so the
                # raw object reached the frontend uncoerced and crashed
                # React ("Objects are not valid as a React child").
                result[key] = _coerce_to_display_text(value)
            continue
        if prop_type != "array":
            continue
        items_type = (prop_schema.get("items") or {}).get("type")
        value = result.get(key)
        if not isinstance(value, list):
            if items_type == "string":
                # Real providers sometimes return a dict keyed by e.g. layer/
                # indicator name instead of a flat array (confirmed live with
                # Gemini on the Stage 1 schema) -- take its values as the
                # per-item bullets rather than stringifying the whole dict
                # into one unreadable blob.
                if isinstance(value, dict):
                    result[key] = [_coerce_to_display_text(item) for item in value.values()]
                else:
                    result[key] = [] if key not in result else [str(value)]
            else:
                result[key] = []
        elif items_type == "string":
            result[key] = [_coerce_to_display_text(item) for item in value]
        # else: array-of-object already a list -- left untouched.
    return result


def validate_report_shape(report: Dict[str, Any]) -> Dict[str, Any]:
    return validate_stage_shape(report, AI_MAP_REPORT_SCHEMA_V2)


def _fallback_compound_hazard_interpretation(evidence: Optional[Dict[str, Any]]) -> List[str]:
    """Grounds the rule-based fallback's compound-hazard bullet in the real,
    already-computed cross_indicator_findings (see app.context.statistical_
    evidence.build_cross_indicator_findings) when available, instead of a
    generic placeholder -- same "no LLM available doesn't mean no real data"
    principle as build_structured_layer_summaries/build_structured_
    indicator_summaries use for the layer/indicator summaries above.
    """
    findings = (evidence or {}).get("cross_indicator_findings") or []

    def areas_with(signal: str) -> List[str]:
        return [f["area"] for f in findings if f.get("signal") == signal and f.get("area") != "National"]

    strong_drought = areas_with("strong_drought")
    strong_wet = areas_with("strong_wet")
    # partial_drought/partial_wet -- real, meaningful (>= CROSS_INDICATOR_
    # MIXED_THRESHOLD) agreement that isn't yet "strong" (see
    # build_cross_indicator_findings) -- confirmed real gap: these used to
    # be silently invisible in this fallback bullet list entirely, neither
    # "strong" nor "mixed" nor mentioned in the final else case.
    partial_drought = areas_with("partial_drought")
    partial_wet = areas_with("partial_wet")
    mixed = areas_with("mixed")
    if not findings:
        return ["No cross-indicator agreement data was available to summarize compound-hazard patterns."]

    lines = []
    if strong_drought:
        lines.append(f"Areas where rainfall, SPI, CDD, and drought probability agree on a strong drought signal: {', '.join(strong_drought)}.")
    if strong_wet:
        lines.append(f"Areas where rainfall, SPI, CWD/Rx-day, and wet probability agree on a strong wetness signal: {', '.join(strong_wet)}.")
    if partial_drought:
        lines.append(f"Areas with real but not yet strong drought-indicator agreement (worth monitoring, not yet at the strong-signal bar): {', '.join(partial_drought)}.")
    if partial_wet:
        lines.append(f"Areas with real but not yet strong wet-indicator agreement (worth monitoring, not yet at the strong-signal bar): {', '.join(partial_wet)}.")
    if mixed:
        lines.append(f"Areas with genuinely mixed or contradicting indicators (review individually before acting): {', '.join(mixed)}.")
    if not lines:
        lines.append("No area currently shows strong, partial, or mixed cross-indicator agreement; conditions are within the near-normal range nationally.")
    return lines


def _fallback_single_priority_area_narrative(item: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic narrative-only entry for ONE real priority-area object,
    matching the real Stage 2 LLM's own expected per-item output shape (see
    STAGE2_SCHEMA). Extracted from _fallback_priority_area_justification_
    narrative's original per-item loop body so the same real, grounded text
    can also be used surgically -- to repair a single area's LLM-authored
    text after a response_validator violation, not just to fall back for
    an entire failed stage (see app.advisory.response_validator.
    repair_item_scoped_violations).
    """
    hazard_label = "drought" if item.get("hazard_type") == "drought" else "wet/flood"
    action_status = item.get("action_status")
    # Real, deterministic action_status decides the intervention label
    # here exactly the same way build_stage2_prompt's DIFFERENTIATOR
    # RULES instruct the real LLM to -- a not_actionable/monitor_only
    # area must not get a full response label just because it's in
    # the top-N ranking (see _action_status's own docstring).
    if action_status == "action":
        intervention = "Drought / water-security response" if item.get("hazard_type") == "drought" else "Flood / wet-hazard mitigation response"
    elif action_status == "preparedness":
        intervention = f"{hazard_label.title()} preparedness monitoring"
    else:
        intervention = "Monitoring only -- not currently actionable this period"
    return {
        "justification_id": item.get("justification_id"),
        "differentiator": (
            # Never cites priority_score (an internal ranking composite
            # with no standalone reader meaning -- see build_stage2_
            # prompt's DIFFERENTIATOR RULES, the same real ban applied
            # here) -- explains the ranking via risk_class/hazard
            # probability/action_status instead, exactly like the real
            # LLM path is instructed to.
            f"Ranks #{item.get('rank')} nationally for {hazard_label} risk, with a risk score of "
            f"{format_number(item.get('risk_score'))} ({item.get('risk_class') or 'unclassified'}) and hazard "
            f"probability of {format_number(item.get('hazard_probability'), 3)}."
            + (f" Real data quality for this area is limited to {item.get('valid_cell_count')} grid cells -- treat as a coarser estimate." if item.get("low_sample_size_warning") else "")
        ),
        "recommended_intervention_type": intervention,
    }


def _fallback_priority_area_justification_narrative(evidence: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic narrative-only entries matching the real Stage 2 LLM's
    own expected output shape (see STAGE2_SCHEMA) -- keyed by justification_
    id so app.api.report_stages's merge step works identically whether the
    narrative came from a real LLM call or this fallback. Grounded in the
    real, already-computed app.context.statistical_evidence.build_priority_
    area_justifications entries, never in request.top_admin_areas (which
    may be at a finer admin level than this evidence engine covers).
    """
    justifications = (evidence or {}).get("priority_area_justifications") or []
    return [_fallback_single_priority_area_narrative(item) for item in justifications]


def _fallback_actionable_areas(evidence: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Real priority areas whose action_status is actually actionable
    (action/preparedness) -- see build_priority_area_justifications --
    the same real gate the LLM path is instructed to use, so the fallback
    never invents advice or an SMS for an area with no real signal to
    support it (confirmed real bug this class of gate fixes: all 5
    wet-ranked areas resolving to not_actionable in a real period, yet
    every one still getting a full response recommendation before).
    """
    justifications = (evidence or {}).get("priority_area_justifications") or []
    return [item for item in justifications if item.get("action_status") in ("action", "preparedness")]


def _fallback_advisory_item(area_entry: Dict[str, Any], action_text: str) -> Dict[str, Any]:
    """One real, structured advisory bullet (see _ADVISORY_ITEM_SCHEMA) --
    area/trigger/evidence/cross_indicator_confidence are always the real
    values from the deterministic priority-area object; only `action` is
    templated text, matching the same shape the real LLM path is
    instructed to return.
    """
    supporting = area_entry.get("supporting_indicators") or []
    return {
        "area": [area_entry.get("area")],
        "action": action_text,
        "trigger": area_entry.get("cross_indicator_signal") or area_entry.get("hazard_type"),
        "evidence": [item.get("indicator") for item in supporting if isinstance(item, dict) and item.get("indicator")],
        "cross_indicator_confidence": area_entry.get("cross_indicator_confidence") or "low",
    }


def _fallback_timescaled_advisory(
    actionable_areas: List[Dict[str, Any]], immediate_text: str, near_term_text: str, preparedness_text: str,
) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "immediate": [_fallback_advisory_item(area, immediate_text) for area in actionable_areas],
        "near_term": [_fallback_advisory_item(area, near_term_text) for area in actionable_areas],
        "preparedness": [_fallback_advisory_item(area, preparedness_text) for area in actionable_areas],
    }


def _fallback_humanitarian_priorities(evidence: Optional[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """monitoring covers EVERY real priority area (even not_actionable ones
    are worth watching); preparedness/pre_positioning/immediate_action are
    real, deterministic tiers of action_status/cross_indicator_confidence,
    each stricter than the last -- never a flat top-N list treated as
    uniformly urgent.
    """
    justifications = (evidence or {}).get("priority_area_justifications") or []
    actionable = [item for item in justifications if item.get("action_status") in ("action", "preparedness")]
    ready = [item for item in justifications if item.get("action_status") == "action"]
    urgent = [item for item in ready if item.get("cross_indicator_confidence") == "high" and not item.get("low_sample_size_warning")]

    return {
        "monitoring": [
            _fallback_advisory_item(area, "Use community ground-truth reports to confirm whether the forecast-based signal is becoming observed impact.")
            for area in justifications
        ],
        "preparedness": [
            _fallback_advisory_item(area, "Coordinate DRM, agriculture, livestock, water, and humanitarian actors around this area ahead of confirmed impact.")
            for area in actionable
        ],
        "pre_positioning": [
            _fallback_advisory_item(area, "Pre-position critical water, agriculture, livestock, and health resources for this area.")
            for area in ready
        ],
        "immediate_action": [
            _fallback_advisory_item(area, "Activate immediate humanitarian response coordination for this area given high-confidence, well-supported evidence.")
            for area in urgent
        ],
    }


def _fallback_sms_messages(
    evidence: Optional[Dict[str, Any]], valid_period: str, language_mismatch_note: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Real, per-actionable-area SMS messages -- confirmed real gap this
    fixes: a single national message was necessarily either too vague to
    act on, or misleading for areas it didn't really apply to, since the
    strongest real signals are highly localized. character_count is added
    later by app.api.report_stages._finalize_sms_messages for the real
    LLM path -- computed directly here since this function IS the
    deterministic path. `language_mismatch_note` (see fallback_report)
    prefixes every message honestly the same way it does for other fields,
    rather than letting a non-English request silently look honored here.
    """
    messages = []
    for area in _fallback_actionable_areas(evidence):
        hazard_label = "drought" if area.get("hazard_type") == "drought" else "flooding/heavy rainfall"
        message = (
            ("[EN fallback] " if language_mismatch_note else "")
            + f"EARLY WARNING: {area.get('area')}. Elevated {hazard_label} risk this period "
            f"({area.get('risk_class') or 'see report'} risk class). Monitor local conditions and follow guidance from local authorities."
        )
        messages.append({
            "area": area.get("area"),
            "audience": "general",
            "hazard": area.get("hazard_type"),
            "valid_period": valid_period,
            "cross_indicator_confidence": area.get("cross_indicator_confidence") or "low",
            "message": message,
            "character_count": len(message),
        })
    return messages


def fallback_report(
    request: AIMapInterpretationRequest,
    retrieved_guidance: List[Dict[str, str]],
    error_message: Optional[str] = None,
    provider_errors: Optional[List[str]] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    language_code = normalize_language_code(request.target_language)
    language_label = get_language_label(language_code)
    # This whole function only ever produces hardcoded ENGLISH sentences --
    # unlike a real LLM call, it has no translation capability. Silently
    # stamping "target_language": language_label on English text falsely
    # implied a Amharic/Oromifa/Tigrinya/Somali request had been honored;
    # this note (surfaced in executive_summary/data_quality_notes/sms below,
    # and content_language_code in _metadata) makes the mismatch explicit
    # instead of hiding it.
    language_mismatch_note = (
        None if language_code == "en" else
        f"This automated summary is shown in English, not {language_label} as requested, because no "
        f"configured AI provider completed successfully -- the rule-based fallback does not translate content."
    )
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

    # Phase 3 #17 -- real structured objects (national_signal, national_mean,
    # highest/lowest_areas, high_or_very_high_area_pct, interpretation, confidence),
    # built from the SAME real `evidence` Stage 1's real LLM call receives
    # (app.context.statistical_evidence.build_national_region_evidence),
    # not the older request.all_map_layer_summaries/all_climate_indicator_
    # summaries this used to read -- so the deterministic fallback is never
    # shape- OR data-source-inconsistent with a real report.
    from app.context.statistical_evidence import (
        build_structured_indicator_summaries,
        build_structured_layer_summaries,
    )

    layer_summary = build_structured_layer_summaries(evidence or {})
    indicator_summary = build_structured_indicator_summaries(evidence or {})

    return {
        "title": "AI Map Interpretation & Advisory",
        "target_language": language_label,
        "executive_summary": (
            f"Forecast window: {forecast_window}; Lead / horizon: {lead}; Admin scope: {admin_scope}; "
            f"Active map group: {active_map_group}; Displayed map: {displayed_map}; "
            f"Active map layer: {active_layer}; Active climate indicator: {active_indicator}; "
            f"Seasonal period: {seasonal_period}; Map product: {seasonal_product}; "
            f"Output language: {language_label}. The report is using the rule-based fallback because no configured AI provider completed successfully."
            + (f" {language_mismatch_note}" if language_mismatch_note else "")
        ),
        "national_spatial_overview": [
            "The Ethiopia-wide interpretation should use all hazard/risk layers and all climate indicators, not only the priority intervention list.",
            "Hotspots should be identified from high-value areas and hotspot regions in the all-layer summaries; lower-value areas should be used as contrast areas.",
        ],
        "layer_by_layer_summary": layer_summary,
        "indicator_by_indicator_summary": indicator_summary,
        "data_quality_notes": [
            "This report is using the rule-based fallback because no configured AI provider completed successfully -- review raw statistics and cross-indicator agreement scores directly for data-quality context.",
            *([language_mismatch_note] if language_mismatch_note else []),
        ],
        "compound_hazard_interpretation": _fallback_compound_hazard_interpretation(evidence),
        "priority_area_justification": _fallback_priority_area_justification_narrative(evidence),
        # Real, structured, per-real-actionable-area objects (see
        # _fallback_timescaled_advisory/_fallback_humanitarian_priorities)
        # -- confirmed real gap this closes: generic national bullets with
        # no real area attached, and every top-N area getting a full
        # response recommendation regardless of real action_status.
        "farmer_advisory": _fallback_timescaled_advisory(
            _fallback_actionable_areas(evidence),
            immediate_text="Conserve available water and strengthen household or farm-level water storage given this area's real risk signal.",
            near_term_text="Adjust planting and field activities according to rainfall onset, dry-spell risk, or wet-spell risk for this area.",
            preparedness_text="Report emerging impacts to local extension, DRM, or community focal points for this area.",
        ),
        "agro_pastoral_advisory": _fallback_timescaled_advisory(
            _fallback_actionable_areas(evidence),
            immediate_text="Prioritize water access and supplementary feed for breeding and lactating animals in this area.",
            near_term_text="Monitor pasture and rangeland condition in this area, and plan herd movement toward better forage/water availability if conditions deteriorate.",
            preparedness_text="Coordinate with local livestock extension and veterinary services on disease risk linked to this area's real hazard signal.",
        ),
        "humanitarian_priorities": _fallback_humanitarian_priorities(evidence),
        "sms_messages": _fallback_sms_messages(evidence, seasonal_period, language_mismatch_note),
        "_metadata": {
            "ai_engine": "rule_based_fallback",
            "provider": None,
            "model": None,
            "requested_provider": normalize_provider(request.requested_provider),
            "requested_model": clean_model_id(request.requested_model) or "auto",
            "used_screenshot": bool(get_map_image_data_url(request)),
            "target_language": language_label,
            "target_language_code": language_code,
            # Always "en" -- this function never translates, regardless of
            # what was requested (see language_mismatch_note above). Lets a
            # caller detect target_language_code != content_language_code
            # without parsing prose.
            "content_language_code": "en",
            "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
            "error": error_message,
            "provider_errors": provider_errors or [],
            # image_count is always 0 here (not len(request.map_images)) --
            # the rule-based fallback never calls any vision API, so no
            # image is ever actually sent, regardless of how many were
            # fetched for a real provider attempt that failed before this.
            **build_verification_metadata(request, 0),
        },
    }


def build_chat_messages(
    system_prompt: str,
    user_prompt: str,
    images: List[Dict[str, str]],
    max_images: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    # Callers are expected to already pass images in priority order (see
    # get_all_image_urls/build_all_map_images -- Hazard/Risk first, then the
    # 5 core climate indicators, then everything else) so capping here
    # (confirmed needed: NVIDIA NIM hard-rejects >16 images per request)
    # keeps the operationally-important ones, not an arbitrary subset.
    if max_images is not None:
        images = images[:max_images]

    content: Any
    if images:
        content = [{"type": "text", "text": user_prompt}]
        for image in images:
            content.append({"type": "image_url", "image_url": {"url": image["data_url"]}})
    else:
        content = user_prompt

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ], len(images)


def call_chat_completions_provider(
    *,
    provider_name: str,
    api_key_env: str,
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    images: List[Dict[str, str]],
    schema: Dict[str, Any],
    request: AIMapInterpretationRequest,
    retrieved_guidance: List[Dict[str, str]],
    extra_headers: Optional[Dict[str, str]] = None,
    max_images: Optional[int] = None,
    max_output_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise ProviderError(f"{api_key_env} is not set.")

    try:
        from openai import OpenAI
    except Exception as exc:
        raise ProviderError("OpenAI Python package is required. Run: pip install openai") from exc

    messages, image_count = build_chat_messages(
        system_prompt + "\nReturn only valid JSON with exactly the requested keys. No Markdown fences.",
        user_prompt,
        images,
        max_images=max_images,
    )
    client = OpenAI(base_url=base_url, api_key=api_key)

    kwargs: Dict[str, Any] = {}
    if extra_headers:
        kwargs["extra_headers"] = extra_headers

    # max_output_tokens overrides the shared AI_MAX_TOKENS default for
    # providers with a small total context window (confirmed: NVIDIA NIM's
    # 16,384-token model rejects the request upfront -- before generating
    # anything -- if input_tokens + max_tokens together exceed that, so a
    # provider with little room for input can't just use the same large
    # ceiling that's safe for a big-context model like GPT-5).
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=float(os.getenv("AI_TEMPERATURE", "0.2")),
        top_p=float(os.getenv("AI_TOP_P", "0.7")),
        max_tokens=max_output_tokens if max_output_tokens is not None else int(os.getenv("AI_MAX_TOKENS", "8000")),
        **kwargs,
    )

    # completion.choices can come back None/empty on a transient provider-side
    # failure (confirmed live: some free-tier OpenRouter models occasionally
    # return this under load) -- a clear ProviderError here lets the normal
    # try/except-then-fallback flow in generate_ai_map_interpretation handle
    # it the same as any other provider failure, instead of a raw, confusing
    # "'NoneType' object is not subscriptable" TypeError.
    if not completion.choices:
        raise ProviderError(f"{provider_name} ({model}) returned no choices in its response.")

    text = completion.choices[0].message.content or ""
    report = validate_stage_shape(parse_json_from_text(text), schema)
    report["_metadata"] = {
        "ai_engine": f"{provider_name}_chat_completions",
        "provider": provider_name,
        "model": model,
        "requested_provider": normalize_provider(request.requested_provider),
        "requested_model": clean_model_id(request.requested_model) or "auto",
        "base_url": base_url,
        "used_screenshot": image_count > 0,
        "target_language": get_language_label(request.target_language),
        "target_language_code": normalize_language_code(request.target_language),
        "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
        "image_count": image_count,
    }
    return report


NVIDIA_MAX_IMAGES = 1  # confirmed via live testing: even 2 images (~6,658 image tokens) plus the
# comprehensive stats/metadata text (~10,300 tokens on its own) exceeds this model's 16,383-token
# context window (16,937 total, still over). 1 image (~3,300 tokens) fits with room to spare. The
# API's own "at most 16 images" cap is a red herring -- the real constraint is total context size.
NVIDIA_MAX_OUTPUT_TOKENS = 4000  # this model's WHOLE context is 16,384 tokens; the API rejects the
# request upfront if input_tokens + max_tokens together exceed that, so it can't share the larger
# AI_MAX_TOKENS default (8000, sized for GPT-5/Gemini's much bigger context windows) -- confirmed
# live: with ~9,400 input tokens (1 image + full comprehensive stats), 8000 was rejected outright
# (400, "requested 17437 tokens"); 4000 leaves comfortable headroom even if input grows somewhat.


def call_nvidia_nim_model(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]]) -> Dict[str, Any]:
    images = get_all_image_urls(request)
    report = call_chat_completions_provider(
        provider_name="nvidia_nim",
        api_key_env="NVIDIA_API_KEY",
        base_url=os.getenv("NVIDIA_BASE_URL", NVIDIA_BASE_URL),
        model=resolve_model_for_provider(request, "nvidia", NVIDIA_DEFAULT_MODEL, "NVIDIA_AI_MODEL"),
        system_prompt=build_system_prompt(request.prompt_version),
        user_prompt=build_user_prompt(request, retrieved_guidance),
        images=images,
        schema=AI_MAP_REPORT_SCHEMA_V2 if request.prompt_version == "v2" else AI_MAP_REPORT_SCHEMA,
        request=request,
        retrieved_guidance=retrieved_guidance,
        max_images=NVIDIA_MAX_IMAGES,
        max_output_tokens=NVIDIA_MAX_OUTPUT_TOKENS,
    )
    report["_metadata"].update(build_verification_metadata(request, report["_metadata"]["image_count"]))
    return report


def call_groq_model(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]], model: Optional[str] = None) -> Dict[str, Any]:
    report = call_chat_completions_provider(
        provider_name="groq",
        api_key_env="GROQ_API_KEY",
        base_url=os.getenv("GROQ_BASE_URL", GROQ_BASE_URL),
        model=model or resolve_model_for_provider(request, "groq", GROQ_DEFAULT_MODEL, "GROQ_AI_MODEL"),
        system_prompt=build_system_prompt(request.prompt_version),
        user_prompt=build_user_prompt(request, retrieved_guidance),
        images=[],
        schema=AI_MAP_REPORT_SCHEMA_V2 if request.prompt_version == "v2" else AI_MAP_REPORT_SCHEMA,
        request=request,
        retrieved_guidance=retrieved_guidance,
    )
    report["_metadata"].update(build_verification_metadata(request, 0))
    return report


def call_openrouter_model(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]]) -> Dict[str, Any]:
    site_url = os.getenv("OPENROUTER_SITE_URL", "https://forecast2action-ai.vercel.app")
    app_title = os.getenv("OPENROUTER_APP_TITLE", "Forecast2Action AI")
    images = get_all_image_urls(request)
    report = call_chat_completions_provider(
        provider_name="openrouter",
        api_key_env="OPENROUTER_API_KEY",
        base_url=os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
        model=resolve_model_for_provider(request, "openrouter", OPENROUTER_DEFAULT_MODEL, "OPENROUTER_AI_MODEL"),
        system_prompt=build_system_prompt(request.prompt_version),
        user_prompt=build_user_prompt(request, retrieved_guidance),
        images=images,
        schema=AI_MAP_REPORT_SCHEMA_V2 if request.prompt_version == "v2" else AI_MAP_REPORT_SCHEMA,
        request=request,
        retrieved_guidance=retrieved_guidance,
        extra_headers={"HTTP-Referer": site_url, "X-OpenRouter-Title": app_title},
    )
    report["_metadata"].update(build_verification_metadata(request, report["_metadata"]["image_count"]))
    return report


def call_openrouter_for_stage(
    request: AIMapInterpretationRequest,
    system_prompt: str,
    user_prompt: str,
    images: List[Dict[str, str]],
    schema: Dict[str, Any],
) -> Dict[str, Any]:
    site_url = os.getenv("OPENROUTER_SITE_URL", "https://forecast2action-ai.vercel.app")
    app_title = os.getenv("OPENROUTER_APP_TITLE", "Forecast2Action AI")
    return call_chat_completions_provider(
        provider_name="openrouter",
        api_key_env="OPENROUTER_API_KEY",
        base_url=os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
        model=resolve_model_for_provider(request, "openrouter", OPENROUTER_DEFAULT_MODEL, "OPENROUTER_AI_MODEL"),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        images=images,
        schema=schema,
        request=request,
        retrieved_guidance=[],
        extra_headers={"HTTP-Referer": site_url, "X-OpenRouter-Title": app_title},
    )


def _call_gemini_raw(gemini_model: str, system_prompt: str, user_prompt: str, images: List[Dict[str, str]]) -> str:
    """Low-level Gemini call: builds contents (text + image parts), calls
    generate_content, returns the raw response text. Shared by the legacy
    single-call path (call_gemini_model) and the staged-workflow path
    (call_gemini_for_stage) so the actual SDK-calling logic exists once.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ProviderError("GEMINI_API_KEY or GOOGLE_API_KEY is not set.")

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise ProviderError("Google Gen AI package is required. Run: pip install google-genai") from exc

    client = genai.Client(api_key=api_key)
    text_prompt = f"{system_prompt}\n\n{user_prompt}\n\nReturn only valid JSON. No Markdown fences."

    contents: List[Any] = [types.Part.from_text(text=text_prompt)]
    for image in images:
        image_bytes, mime_type = data_url_to_bytes(image["data_url"])
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

    try:
        response = client.models.generate_content(
            model=gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=float(os.getenv("AI_TEMPERATURE", "0.2")),
                top_p=float(os.getenv("AI_TOP_P", "0.7")),
                max_output_tokens=int(os.getenv("AI_MAX_TOKENS", "8000")),
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
                "max_output_tokens": int(os.getenv("AI_MAX_TOKENS", "8000")),
            },
        )
    return response.text or ""


def _gemini_metadata(
    request: AIMapInterpretationRequest,
    gemini_model: str,
    image_count: int,
    retrieved_guidance: List[Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "ai_engine": "gemini_generate_content",
        "provider": "gemini",
        "model": gemini_model,
        "requested_provider": normalize_provider(request.requested_provider),
        "requested_model": clean_model_id(request.requested_model) or "auto",
        "used_screenshot": image_count > 0,
        "target_language": get_language_label(request.target_language),
        "target_language_code": normalize_language_code(request.target_language),
        "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
        "image_count": image_count,
    }


def call_gemini_model(
    request: AIMapInterpretationRequest,
    retrieved_guidance: List[Dict[str, str]],
    model: Optional[str] = None,
) -> Dict[str, Any]:
    gemini_model = model or resolve_model_for_provider(request, "gemini", GEMINI_DEFAULT_MODEL, "GEMINI_AI_MODEL")
    system_prompt = build_system_prompt(request.prompt_version)
    user_prompt = build_user_prompt(request, retrieved_guidance)
    images = get_all_image_urls(request)

    text = _call_gemini_raw(gemini_model, system_prompt, user_prompt, images)
    report = validate_report_shape(parse_json_from_text(text))
    report["_metadata"] = {
        **_gemini_metadata(request, gemini_model, len(images), retrieved_guidance),
        **build_verification_metadata(request, len(images)),
    }
    return report


def call_gemini_for_stage(
    request: AIMapInterpretationRequest,
    system_prompt: str,
    user_prompt: str,
    images: List[Dict[str, str]],
    schema: Dict[str, Any],
    model: Optional[str] = None,
    default_model: str = GEMINI_DEFAULT_MODEL,
) -> Dict[str, Any]:
    # No env_name here (unlike the legacy call_gemini_model) -- per-stage
    # tiering (see GEMINI_MODEL_TIERS) is a request-time concept, not a
    # global env override; default_model already carries the right tier's
    # choice, and the user's own explicit request.requested_model (if set)
    # still wins via resolve_model_for_provider's own precedence.
    gemini_model = model or resolve_model_for_provider(request, "gemini", default_model)
    text = _call_gemini_raw(gemini_model, system_prompt, user_prompt, images)
    report = validate_stage_shape(parse_json_from_text(text), schema)
    report["_metadata"] = _gemini_metadata(request, gemini_model, len(images), [])
    return report


def _call_openai_raw(
    client: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
    images: List[Dict[str, str]],
    schema: Dict[str, Any],
    schema_name: str,
) -> Tuple[str, str, Optional[str]]:
    """Low-level OpenAI Responses-API call: tries strict json_schema
    structured output first, falls back to unstructured JSON parsing on any
    schema error. Returns (output_text, engine_name, structured_error_str).
    Shared by the legacy single-call path (call_openai_model) and the
    staged-workflow path (call_openai_for_stage).
    """
    content: List[Dict[str, Any]] = [{"type": "input_text", "text": user_prompt}]
    for image in images:
        content.append({"type": "input_image", "image_url": image["data_url"], "detail": "low"})

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
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
            max_output_tokens=int(os.getenv("AI_MAX_TOKENS", "8000")),
        )
        return response.output_text, "openai_responses_api", None
    except Exception as structured_error:
        fallback_content: List[Dict[str, Any]] = [
            {
                "type": "input_text",
                "text": f"{system_prompt}\n\n{user_prompt}\n\nReturn only valid JSON. Do not include Markdown fences.",
            }
        ]
        for image in images:
            fallback_content.append({"type": "input_image", "image_url": image["data_url"], "detail": "low"})
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": fallback_content}],
            max_output_tokens=int(os.getenv("AI_MAX_TOKENS", "8000")),
        )
        return response.output_text, "openai_responses_api_json_fallback", str(structured_error)


def _openai_client() -> Any:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ProviderError("OPENAI_API_KEY is not set.")
    try:
        from openai import OpenAI
    except Exception as exc:
        raise ProviderError("OpenAI Python package is required. Run: pip install openai") from exc
    return OpenAI(api_key=api_key)


def call_openai_model(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]]) -> Dict[str, Any]:
    client = _openai_client()
    model = resolve_model_for_provider(request, "openai", OPENAI_DEFAULT_MODEL, "OPENAI_MAP_AI_MODEL")
    system_prompt = build_system_prompt(request.prompt_version)
    user_prompt = build_user_prompt(request, retrieved_guidance)
    images = get_all_image_urls(request)
    schema = AI_MAP_REPORT_SCHEMA_V2 if request.prompt_version == "v2" else AI_MAP_REPORT_SCHEMA

    output_text, engine, structured_error = _call_openai_raw(
        client, model, system_prompt, user_prompt, images, schema, "ai_map_interpretation_report"
    )
    report = validate_report_shape(parse_json_from_text(output_text))
    if structured_error:
        report.setdefault("_metadata", {})["structured_output_error"] = structured_error

    report["_metadata"] = {
        **report.get("_metadata", {}),
        "ai_engine": engine,
        "provider": "openai",
        "model": model,
        "requested_provider": normalize_provider(request.requested_provider),
        "requested_model": clean_model_id(request.requested_model) or "auto",
        "used_screenshot": bool(images),
        "target_language": get_language_label(request.target_language),
        "target_language_code": normalize_language_code(request.target_language),
        "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
        **build_verification_metadata(request, len(images)),
    }
    return report


def call_openai_for_stage(
    request: AIMapInterpretationRequest,
    system_prompt: str,
    user_prompt: str,
    images: List[Dict[str, str]],
    schema: Dict[str, Any],
) -> Dict[str, Any]:
    client = _openai_client()
    model = resolve_model_for_provider(request, "openai", OPENAI_DEFAULT_MODEL, "OPENAI_MAP_AI_MODEL")

    output_text, engine, structured_error = _call_openai_raw(
        client, model, system_prompt, user_prompt, images, schema, "ai_map_interpretation_stage_report"
    )
    report = validate_stage_shape(parse_json_from_text(output_text), schema)
    report["_metadata"] = {
        "ai_engine": engine,
        "provider": "openai",
        "model": model,
        "requested_provider": normalize_provider(request.requested_provider),
        "requested_model": clean_model_id(request.requested_model) or "auto",
        "used_screenshot": bool(images),
        "target_language": get_language_label(request.target_language),
        "target_language_code": normalize_language_code(request.target_language),
        "image_count": len(images),
    }
    if structured_error:
        report["_metadata"]["structured_output_error"] = structured_error
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

        # 1. Gemini Flash-Lite / Flash first -- confirmed via live testing
        # (see NVIDIA_MAX_IMAGES/NVIDIA_MAX_OUTPUT_TOKENS comments above)
        # that Gemini reliably handles the FULL comprehensive payload (all
        # 32 map images) in 10-40s, free, while NVIDIA's nano model needs
        # aggressive capping to just 1 image and is still slower overall.
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
                    result["_metadata"]["provider_attempts"] = ["gemini"]
                    result["_metadata"]["provider_errors"] = errors
                    return result
        else:
            errors.append("Gemini skipped: GEMINI_API_KEY/GOOGLE_API_KEY is not set.")

        # 2. OpenRouter next -- every model in its dropdown list is
        # confirmed (live-tested) to handle the full comprehensive payload.
        # NVIDIA and Groq were removed from this automatic chain: NVIDIA
        # only ever manages 1 image (its whole context is 16,384 tokens,
        # see NVIDIA_MAX_IMAGES/NVIDIA_MAX_OUTPUT_TOKENS below), and Groq
        # hard-fails on its free-tier token-per-minute limit for this much
        # text regardless of images. Both functions/explicit-provider
        # selection paths still exist below for direct/advanced use --
        # they're just no longer tried automatically.
        if os.getenv("OPENROUTER_API_KEY"):
            result = try_provider("OpenRouter free", lambda: call_openrouter_model(request, retrieved_guidance), errors)
            if result:
                result.setdefault("_metadata", {})["provider_chain"] = "free_auto"
                result["_metadata"]["provider_attempts"] = ["gemini", "openrouter"]
                result["_metadata"]["provider_errors"] = errors
                return result
        else:
            errors.append("OpenRouter skipped: OPENROUTER_API_KEY is not set.")

        # 3. OpenAI if billing is available/configured.
        if os.getenv("OPENAI_API_KEY"):
            result = try_provider("OpenAI", lambda: call_openai_model(request, retrieved_guidance), errors)
            if result:
                result.setdefault("_metadata", {})["provider_chain"] = "free_auto"
                result["_metadata"]["provider_attempts"] = ["gemini", "openrouter", "openai"]
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
        # Groq is configured as text-only (call_groq_model always passes
        # include_image=False) -- proceeds without any image rather than
        # blocking the request, now that images (the comprehensive map set,
        # see populate_comprehensive_map_data) are attached to every report
        # by default rather than only when a user explicitly enables a
        # screenshot. The response's own _metadata.image_count truthfully
        # reports 0 for this provider either way.
        return call_groq_model(request, retrieved_guidance)
    if provider == "openrouter":
        return call_openrouter_model(request, retrieved_guidance)
    if provider == "openai":
        return call_openai_model(request, retrieved_guidance)

    raise ProviderError(f"Unsupported AI_PROVIDER='{provider}'. Use free_auto, openai, nvidia, gemini, groq, or openrouter.")


# Step 9 -- per-stage model tier. "lite" is the existing default (fast,
# free, fine for JSON transformation / field extraction / short summaries
# / translation). "strong" is used ONLY for Stage 2 (integrated synthesis
# -- reconciling conflicting dry/wet signals, hazard-exposure-vulnerability
# relationships, real priority rankings): tries gemini-flash-latest
# (Google's non-lite Flash tier, still free) before flash-lite, the
# reverse of "lite"'s order. Deliberately stays within the free tier --
# OpenRouter/OpenAI fallback models are UNCHANGED for both tiers, per
# explicit confirmation, so this never silently increases cost on the
# automatic path (same "never add paid models to the automatic chain
# without confirmation" principle as the free_auto NVIDIA/Groq removal).
GEMINI_MODEL_TIERS: Dict[str, List[str]] = {
    "lite": [os.getenv("GEMINI_AI_MODEL", GEMINI_DEFAULT_MODEL), os.getenv("GEMINI_FALLBACK_MODEL", GEMINI_FALLBACK_MODEL)],
    "strong": [os.getenv("GEMINI_FALLBACK_MODEL", GEMINI_FALLBACK_MODEL), os.getenv("GEMINI_AI_MODEL", GEMINI_DEFAULT_MODEL)],
}


def call_configured_ai_provider_for_stage(
    request: AIMapInterpretationRequest,
    system_prompt: str,
    user_prompt: str,
    images: List[Dict[str, str]],
    schema: Dict[str, Any],
    model_tier: str = "lite",
) -> Dict[str, Any]:
    """Staged-workflow counterpart of call_configured_ai_provider: same
    Gemini -> OpenRouter -> OpenAI fallback chain (NVIDIA/Groq intentionally
    excluded here too, matching this session's earlier Tier-1-only UI
    decision -- NVIDIA's 1-image cap and Groq's rate limit make them a poor
    fit for a workflow where Stage 1 still needs up to 16 images), but each
    stage call carries its OWN prompt/images/schema instead of deriving a
    single whole-request payload internally. model_tier selects which
    GEMINI_MODEL_TIERS list to try (see above) -- OpenRouter/OpenAI stay
    identical regardless of tier.
    """
    provider = normalize_provider(request.requested_provider or os.getenv("AI_PROVIDER", AI_PROVIDER))
    gemini_models = GEMINI_MODEL_TIERS.get(model_tier, GEMINI_MODEL_TIERS["lite"])

    if provider in {"auto", "free_auto", "multi", "multi_provider"}:
        errors: List[str] = []

        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            for gemini_model in gemini_models:
                if not gemini_model:
                    continue
                result = try_provider(
                    f"Gemini {gemini_model}",
                    lambda m=gemini_model: call_gemini_for_stage(request, system_prompt, user_prompt, images, schema, model=m),
                    errors,
                )
                if result:
                    result["_metadata"]["provider_chain"] = "free_auto"
                    result["_metadata"]["provider_attempts"] = ["gemini"]
                    result["_metadata"]["provider_errors"] = errors
                    result["_metadata"]["model_tier"] = model_tier
                    return result
        else:
            errors.append("Gemini skipped: GEMINI_API_KEY/GOOGLE_API_KEY is not set.")

        if os.getenv("OPENROUTER_API_KEY"):
            result = try_provider(
                "OpenRouter free",
                lambda: call_openrouter_for_stage(request, system_prompt, user_prompt, images, schema),
                errors,
            )
            if result:
                result["_metadata"]["provider_chain"] = "free_auto"
                result["_metadata"]["provider_attempts"] = ["gemini", "openrouter"]
                result["_metadata"]["provider_errors"] = errors
                result["_metadata"]["model_tier"] = model_tier
                return result
        else:
            errors.append("OpenRouter skipped: OPENROUTER_API_KEY is not set.")

        if os.getenv("OPENAI_API_KEY"):
            result = try_provider(
                "OpenAI",
                lambda: call_openai_for_stage(request, system_prompt, user_prompt, images, schema),
                errors,
            )
            if result:
                result["_metadata"]["provider_chain"] = "free_auto"
                result["_metadata"]["provider_attempts"] = ["gemini", "openrouter", "openai"]
                result["_metadata"]["provider_errors"] = errors
                result["_metadata"]["model_tier"] = model_tier
                return result
        else:
            errors.append("OpenAI skipped: OPENAI_API_KEY is not set.")

        raise ProviderError(" | ".join(errors) if errors else "No provider completed successfully.")

    if provider == "gemini":
        result = call_gemini_for_stage(request, system_prompt, user_prompt, images, schema, default_model=gemini_models[0])
        result["_metadata"]["model_tier"] = model_tier
        return result
    if provider == "openrouter":
        result = call_openrouter_for_stage(request, system_prompt, user_prompt, images, schema)
        result["_metadata"]["model_tier"] = model_tier
        return result
    if provider == "openai":
        result = call_openai_for_stage(request, system_prompt, user_prompt, images, schema)
        result["_metadata"]["model_tier"] = model_tier
        return result

    raise ProviderError(
        f"Unsupported AI_PROVIDER='{provider}' for the staged workflow. Use free_auto, gemini, openrouter, or openai."
    )


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
            "gemini_flash_lite_or_flash",
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


def resolve_report_period(request: AIMapInterpretationRequest) -> str:
    """Same period-resolution order used by populate_comprehensive_map_data
    and build_user_prompt for period display -- extracted so
    app.api.report_stages can resolve the identical period for its own
    build_national_region_evidence() call without duplicating this chain.
    """
    return (
        request.forecast_selection.seasonalPeriod
        or request.map_context.seasonal_period
        or request.forecast_selection.lead
        or "JJAS"
    )


async def populate_comprehensive_map_data(request: AIMapInterpretationRequest) -> AIMapInterpretationRequest:
    """Fills all_map_layer_summaries / all_climate_indicator_summaries /
    map_images from EVERY Hazard/Risk layer and climate-indicator/product
    combo for the resolved period -- ONLY where the request didn't already
    provide them (same additive convention as merge_envelope_into_request),
    so old callers that explicitly pass their own narrower data are never
    overwritten. Called unconditionally for every report (not gated on
    context_id) so "send everything" doesn't depend on a context ever
    having been built -- the period is resolved directly from
    forecast_selection/map_context, the same fields build_user_prompt
    already reads for its own period display logic.
    """
    from app.context.spatial_summary import (
        build_all_climate_indicator_summaries,
        build_all_layer_summaries,
        build_all_map_images,
    )

    period = resolve_report_period(request)

    updates: Dict[str, Any] = {}

    if not request.all_map_layer_summaries:
        layer_summaries = build_all_layer_summaries(period)
        updates["all_map_layer_summaries"] = {item["layer_value"]: item for item in layer_summaries}

    if not request.all_climate_indicator_summaries:
        indicator_summaries = build_all_climate_indicator_summaries(period)
        updates["all_climate_indicator_summaries"] = {
            f"{item['indicator']}_{item['product']}": item for item in indicator_summaries
        }

    if not request.map_images:
        try:
            updates["map_images"] = await build_all_map_images(period)
        except Exception:
            logger.exception("Failed to build comprehensive map images for period=%s", period)
            updates["map_images"] = []

    return request.model_copy(update=updates) if updates else request


@router.post("/map-interpretation")
async def generate_ai_map_interpretation(request: AIMapInterpretationRequest) -> Dict[str, Any]:
    request = await populate_comprehensive_map_data(request)

    envelope = None
    if request.context_id:
        from app.context.repository import get_repository

        envelope = get_repository().get(request.context_id)
        if envelope:
            request = merge_envelope_into_request(envelope, request)

    # Real, deterministic national evidence -- cache-backed (cheap on a
    # cache hit, which run_staged_report_generation's own internal call
    # below will also hit) -- computed here specifically so retrieve_
    # guidance can scope retrieval to real actionable hazard types instead
    # of dashboard UI state (see retrieve_guidance's docstring).
    try:
        from app.context.statistical_evidence import build_national_region_evidence

        evidence_for_retrieval = build_national_region_evidence(
            resolve_report_period(request).lower(), admin_level="admin1", use_cache=True,
        )
    except Exception:
        logger.exception("Failed to build evidence for retrieval scoping -- falling back to UI-state-only query")
        evidence_for_retrieval = None

    retrieved_guidance = retrieve_guidance(request, evidence=evidence_for_retrieval)
    try:
        from app.api.report_stages import run_staged_report_generation

        report = run_staged_report_generation(request, retrieved_guidance)
    except Exception as error:
        provider_errors = []
        text = str(error)
        if " | " in text:
            provider_errors = text.split(" | ")
        report = validate_report_shape(
            fallback_report(
                request=request,
                retrieved_guidance=retrieved_guidance,
                error_message=str(error),
                provider_errors=provider_errors,
            )
        )

    if envelope:
        from app.retrieval.citation_builder import build_citations

        # Citations must be deterministic, not LLM-generated: none of the
        # non-OpenAI-strict-schema providers are ever told to emit
        # evidence_citations (their prompt only lists the v1 report keys --
        # see build_user_prompt), and letting the LLM invent knowledge_ids
        # would violate the "LLM must never invent institutions/actions"
        # rule. Overwrite whatever the provider returned with the real,
        # already-retrieved knowledge items from the envelope instead.
        report["evidence_citations"] = build_citations(envelope.knowledge.retrieved_items)

        # Content validation against the envelope's own narrower data
        # (validate_against_context) was removed -- it was fully superseded
        # by validate_against_evidence, which already ran unconditionally
        # inside run_staged_report_generation against the REAL evidence the
        # report was generated from (every real priority area, not just this
        # envelope's single selected area), and was producing confirmed
        # false positives on legitimately-cited real numbers as a result.

    return report


def merge_envelope_into_request(
    envelope: "DecisionContextEnvelope", request: AIMapInterpretationRequest,
) -> AIMapInterpretationRequest:
    """Fills top_admin_areas/all_map_layer_summaries/all_climate_indicator_summaries
    from a real Decision Context Envelope ONLY where the request didn't
    already provide them -- old callers that explicitly pass their own data
    are never overwritten. Also switches the default prompt_version to "v2"
    (the context-aware prompt with the "must not" rules) unless the caller
    explicitly requested a different version.

    This is the concrete fix for the gap where this endpoint's evidence was
    sourced from the OLD synthetic-grid /api/intervention-ranking instead of
    the REAL /api/hazard-risk/ranking data the Priority Intervention Areas
    table actually renders -- see app.context.ai_report_adapter.
    """
    from app.context.ai_report_adapter import (
        build_legacy_climate_indicator_summaries,
        build_legacy_layer_summaries,
        build_top_admin_areas,
    )

    updates: Dict[str, Any] = {}

    if not request.top_admin_areas:
        updates["top_admin_areas"] = build_top_admin_areas(
            rank_by=envelope.hazard_evidence.layer_value,
            period=envelope.forecast.hazard_risk_period,
            admin_level=envelope.geography.admin_level,
            top_n=envelope.forecast.top_n,
            threshold=envelope.forecast.threshold,
            region_id=envelope.geography.region_id,
            zone_id=envelope.geography.zone_id,
        )

    if not request.all_map_layer_summaries:
        updates["all_map_layer_summaries"] = build_legacy_layer_summaries(
            envelope.forecast.hazard_risk_period, envelope.hazard_evidence.hazard_type or "drought",
        )

    if not request.all_climate_indicator_summaries:
        updates["all_climate_indicator_summaries"] = build_legacy_climate_indicator_summaries(
            envelope.forecast.hazard_risk_period,
        )

    if request.prompt_version is None:
        updates["prompt_version"] = "v2"

    updates["context_id"] = envelope.context_id

    return request.model_copy(update=updates)
