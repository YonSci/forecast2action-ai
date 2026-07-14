import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/ai", tags=["AI Map Interpretation"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"
DEFAULT_MODEL = os.getenv("OPENAI_MAP_AI_MODEL", "gpt-5.6-luna")

LANGUAGE_LABELS = {
    "en": "English",
    "am": "Amharic",
    "om": "Oromifa / Afaan Oromo",
    "ti": "Tigrinya",
    "so": "Somali",
    "sw": "Swahili",
    "fr": "French",
    "ar": "Arabic",
}


def normalize_language_code(value: Optional[str]) -> str:
    text = str(value or "en").strip().lower()

    if text in {"am", "amh", "amharic", "am-et", "አማርኛ"}:
        return "am"
    if text in {"om", "orm", "oromo", "oromifa", "afaan oromo", "afan oromo", "or"}:
        return "om"
    if text in {"ti", "tir", "tig", "tigrinya", "tigrigna", "ትግርኛ"}:
        return "ti"
    if text in {"so", "som", "somali", "af-soomaali", "af soomaali", "soomaali"}:
        return "so"
    if text in {"sw", "swa", "swahili", "kiswahili"}:
        return "sw"
    if text in {"fr", "fre", "fra", "french", "français", "francais"}:
        return "fr"
    if text in {"ar", "ara", "arabic", "العربية"}:
        return "ar"
    if text in {"en", "eng", "english", "en-us", "en-gb"}:
        return "en"

    return text or "en"


def language_label(value: Optional[str]) -> str:
    return LANGUAGE_LABELS.get(normalize_language_code(value), "English")


def language_instruction(value: Optional[str]) -> str:
    code = normalize_language_code(value)
    if code == "am":
        return "Write the entire report in Amharic using Ethiopic script. Do not write the report in English. Keep administrative place names as provided when appropriate."
    if code == "om":
        return "Write the entire report in Oromifa / Afaan Oromo using Latin script. Do not write the report in English. Keep administrative place names as provided when appropriate."
    if code == "ti":
        return "Write the entire report in Tigrinya using Ethiopic script. Do not write the report in English. Keep administrative place names as provided when appropriate."
    if code == "so":
        return "Write the entire report in Somali using Latin script. Do not write the report in English. Keep administrative place names as provided when appropriate."
    if code == "sw":
        return "Write the entire report in Swahili using Latin script. Do not write the report in English. Keep administrative place names as provided when appropriate."
    if code == "fr":
        return "Write the entire report in French. Do not write the report in English. Keep administrative place names as provided when appropriate."
    if code == "ar":
        return "Write the entire report in Arabic. Do not write the report in English. Keep administrative place names as provided when appropriate."
    return "Write the entire report in English. Keep administrative place names as provided when appropriate."


class ForecastSelection(BaseModel):
    forecastScale: Optional[str] = "subseasonal"
    lead: Optional[str] = "week_1"
    layer: Optional[str] = "risk_score"
    indicator: Optional[str] = "spi"


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


AI_MAP_REPORT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "target_language": {"type": "string"},
        "executive_summary": {"type": "string"},
        "spatial_interpretation": {"type": "array", "items": {"type": "string"}},
        "highest_risk_areas": {"type": "array", "items": {"type": "string"}},
        "climate_indicator_interpretation": {"type": "array", "items": {"type": "string"}},
        "cross_layer_insights": {"type": "array", "items": {"type": "string"}},
        "impact_assessment": {"type": "array", "items": {"type": "string"}},
        "farmer_advisory": {"type": "array", "items": {"type": "string"}},
        "policy_recommendations": {"type": "array", "items": {"type": "string"}},
        "humanitarian_priorities": {"type": "array", "items": {"type": "string"}},
        "confidence_note": {"type": "string"},
        "sms_summary": {"type": "string"},
    },
    "required": [
        "title",
        "target_language",
        "executive_summary",
        "spatial_interpretation",
        "highest_risk_areas",
        "climate_indicator_interpretation",
        "cross_layer_insights",
        "impact_assessment",
        "farmer_advisory",
        "policy_recommendations",
        "humanitarian_priorities",
        "confidence_note",
        "sms_summary",
    ],
}


def request_to_dict(request: AIMapInterpretationRequest) -> Dict[str, Any]:
    if hasattr(request, "model_dump"):
        return request.model_dump()
    return request.dict()


def title_case(value: Any) -> str:
    if value is None:
        return "N/A"
    text = str(value).replace("_", " ").strip()
    if not text:
        return "N/A"
    return " ".join(word[:1].upper() + word[1:].lower() for word in text.split())


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


def normalize_data_url(map_image_base64: Optional[str]) -> Optional[str]:
    if not map_image_base64:
        return None
    value = map_image_base64.strip()
    if value.startswith("data:image/"):
        return value
    return f"data:image/png;base64,{value}"


def get_request_language_code(request: AIMapInterpretationRequest) -> str:
    return normalize_language_code(request.target_language or request.target_language_label)


def get_request_language_label(request: AIMapInterpretationRequest) -> str:
    return LANGUAGE_LABELS.get(get_request_language_code(request), language_label(request.target_language_label))


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
        get_request_language_label(request),
        json.dumps(request.all_map_layer_summaries, ensure_ascii=False)[:3000],
        json.dumps(request.all_climate_indicator_summaries, ensure_ascii=False)[:3000],
    ]
    for item in request.top_admin_areas[:8]:
        query_parts.extend([item.get("hazard"), item.get("risk_level"), item.get("region"), item.get("zone"), item.get("woreda")])

    query_tokens = set(tokenize(" ".join(str(part) for part in query_parts if part)))
    scored = []
    for document in documents:
        doc_text = document["title"] + "\n" + document["text"]
        doc_tokens = set(tokenize(doc_text))
        overlap = len(query_tokens.intersection(doc_tokens))
        bonus = 0
        lowered = doc_text.lower()
        for keyword in ["drought", "dry", "flood", "wet", "livestock", "agriculture", "humanitarian", "sms", "water", "policy", "pasture"]:
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


def build_system_prompt(request: AIMapInterpretationRequest) -> str:
    return f"""
You are an expert climate risk, agriculture, livestock, agro-pastoralism, and humanitarian early-warning analyst.

Your job is to interpret Forecast2Action AI hazard/risk map layers and climate indicator maps for Ethiopia and convert them into actionable advice.

LANGUAGE REQUIREMENT:
{language_instruction(get_request_language_code(request))}

Important rules:
- Use the structured JSON map summaries as the source of truth.
- Use the optional map screenshot only as supporting visual context.
- Analyze ALL provided map layers: hazard, risk score, hazard probability, exposure, and vulnerability.
- Analyze ALL provided climate indicators: SPI, rainfall anomaly, rainfall percentile, CDD, and CWD.
- Do not invent regions, zones, or woredas that are not provided in the structured data.
- Identify the administrative areas with highest risk and explain why.
- Explain likely impacts for rainfed agriculture, agro-pastoralist communities, livestock, and humanitarian operations.
- Provide practical recommendations for farmers, policymakers, and humanitarian/DRM actors.
- Mention uncertainty and recommend local verification.
- Return only valid JSON matching the requested schema.
""".strip()


def build_user_prompt(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]]) -> str:
    code = get_request_language_code(request)
    label = get_request_language_label(request)
    payload = request_to_dict(request)
    payload.pop("map_image_base64", None)

    return f"""
Generate a localized AI Map Interpretation & Advisory report.

TARGET LANGUAGE:
- Language code: {code}
- Language label: {label}
- Strict instruction: {language_instruction(code)}
- The title, executive summary, all bullet points, confidence note, and SMS summary must be in {label}.

CONTEXT & METADATA:
- Forecast window: {request.forecast_selection.forecastScale}
- Lead time: {request.forecast_selection.lead}
- Current seasonal context: {request.map_context.current_seasonal_context or request.map_context.seasonal_context or "Not specified"}
- Active map layer selected in dashboard: {request.forecast_selection.layer}
- Active climate indicator selected in dashboard: {request.forecast_selection.indicator}
- Hazard type: {request.map_context.hazard_type or "Infer from data if available"}
- Admin scope: {request.map_context.admin_scope or "All Ethiopia or selected administrative boundary"}
- Audience: {request.audience_focus}

TASK:
1. Interpret all hazard/risk map layers: hazard, risk score, hazard probability, exposure, vulnerability.
2. Interpret all climate indicator maps: Standardized Precipitation Index, rainfall anomaly, rainfall percentile, consecutive dry days, consecutive wet days.
3. Identify specific regions, zones, and woredas facing the highest risks.
4. Explain what this means for rainfed agriculture, agro-pastoral communities, livestock, and local livelihoods.
5. Provide 3-4 concrete recommendations for local farmers and agro-pastoral communities.
6. Provide 3-4 recommendations for regional policymakers and DRM actors.
7. Provide 2-3 high-level humanitarian/resource allocation priorities.
8. Explain cross-layer insights, for example whether risk is driven by hazard probability, exposure, vulnerability, or climate indicators.
9. Keep the tone professional, objective, and easy to read.

STRUCTURED MAP DATA AND ALL-LAYER SUMMARIES:
{json.dumps(payload, indent=2, ensure_ascii=False)}

RETRIEVED EARLY-ACTION GUIDANCE:
{json.dumps(retrieved_guidance, indent=2, ensure_ascii=False)}
""".strip()


def localized_fallback_text(code: str, main_area: str, hazard: str, lead: str) -> Dict[str, Any]:
    if code == "om":
        return {
            "title": "Hiikkaa Kaartaa AI fi Gorsa Tarkaanfii",
            "executive_summary": f"Raaga {lead} keessatti naannoo {main_area} irratti mallattoon balaa {hazard} mulʼata. Murtiin hojiirra oolmaa dura ragaan naannoo irraa mirkaneeffamuu qaba.",
            "spatial": ["Naannoon sadarkaa olaanaa qabu tarree bulchiinsa kennamerratti hundaaʼe adda baafameera.", "Balaan yeroo carraan balaa, saaxilamummaa fi miidhama waliin walitti dhufan cimaa taʼa."],
            "climate": ["SPI, jijjiirama roobaa, persentaayilii roobaa, CDD fi CWD waliin ilaalamuu qabu.", "CDD olkaʼaa fi roobni gadi buʼaan yaaddoo goginsaa agarsiisuu dandaʼa."],
            "impact": ["Qonna rooba irratti hirkatu irratti hanqinni jiidhaa mudachuu dandaʼa.", "Hawaasni horsiisee-bulaa bishaanii fi margaa irratti dhiibbaa arguu dandaʼa."],
            "farmer": ["Bishaan argamu qusachuu fi kuusaa bishaanii cimsuu.", "Yeroo facaasa rooba mirkanaaʼaa irratti hundeessuu.", "Haala margaa, midhaanii fi loonii hordofuu.", "Rakkoo mulʼatu qaama naannoo beeksisuu."],
            "policy": ["Aanaalee balaa olaanaa qaban keessatti haala jiru saʼaatii 24-72 keessatti mirkaneessuu.", "Qaamolee qonnaa, beeyladaa, bishaanii fi DRM walitti fiduu.", "Ergaa akeekkachiisaa afaan naannootiin qopheessuu.", "Gabaasa hawaasaa fayyadamuun tarkaanfii haaromsuu."],
            "human": ["Bishaan, tajaajila beeyladaa fi hordoffii margaa dursanii qopheessuu.", "Qabeenya gara naannoo saaxilamummaa fi miidhamummaan olaanaa taʼetti qajeelchuu.", "Ragaa lafa irraa argamuun murtii cimsuu."],
            "confidence": "Kun gorsa buʼuura seera fallback ti. Murtii hojii dura ragaan naannoo irraa mirkaneeffamuu qaba.",
            "sms": f"AKEEKKACHIISA: {main_area} keessatti balaa {hazard} {lead} irratti hordofaa. Bishaan qusadhaa, haala naannoo gabaasaa, qajeelfama qaamolee naannoo hordofaa.",
        }
    if code == "ti":
        return {
            "title": "ትርጓመ ካርታ AIን ምኽሪ ተግባርን",
            "executive_summary": f"ናይ {lead} ትንበያ ኣብ {main_area} ሓደጋ {hazard} ክህሉ ከምዝኽእል የመልክት። ቅድሚ ውሳነ ምውሳድ ናይ ከባቢ ምርግጋጽ የድሊ።",
            "spatial": ["እቶም ብልዑል ሓደጋ ዝተለዩ ከባቢታት ካብ ዝተዋህበ ዝርዝር ምምሕዳር ተመርኲሶም እዮም።", "ሓደጋ ኣብ ዝለዓለ ዕድል ሓደጋ፣ ተጋላጽነትን ተጎዳእነትን ምስ ተደራረበ ይዓቢ።"],
            "climate": ["SPI፣ ለውጢ ዝናብ፣ ፐርሰንታይል ዝናብ፣ CDDን CWDን ብሓባር ክምርመሩ ይግባእ።", "CDD ምውሳኽን ዝናብ ምንካይን ሓደጋ ድርቂ ከመልክት ይኽእል።"],
            "impact": ["ብዝናብ ዝምራሕ ሕርሻ ጸገም ርጥበት ክረክብ ይኽእል።", "ማሕበረሰብ ሓረስቶትን ኣርብቶ ኣደርን ኣብ ማይን መግቢ እንስሳን ጸቕጢ ክረክብ ይኽእል።"],
            "farmer": ["ማይ ምቑጣብን መኽዘን ማይ ምጥንኻርን።", "ግዜ ዘርኢ ከከም እምነት ዝናብ ምውሳን።", "ኩነታት ሰብልን እንስሳን ምክትታል።", "ዝተራእየ ጸገም ንባለስልጣን ከባቢ ምሕባር።"],
            "policy": ["ኣብ ልዑል ሓደጋ ዘለዉ ወረዳታት ኩነታት ኣብ 24-72 ሰዓታት ምርግጋጽ።", "ቢሮታት ሕርሻ፣ እንስሳ፣ ማይን DRMን ምውህሃድ።", "መልእኽቲ ምትሕስሳብ ብቋንቋ ከባቢ ምድላው።", "ጸብጻብ ማሕበረሰብ ተጠቒምካ ተግባር ምምሕያሽ።"],
            "human": ["ምክትታል ነጥቢ ማይ፣ ደገፍ እንስሳን መግብን ቀዳምነት ምሃብ።", "ሃብቲ ናብ ልዑል ተጋላጽነት ዘለዎ ከባቢ ምቕናዕ።", "ውሳነ ብምርግጋጽ መሬት ምድጋፍ።"],
            "confidence": "እዚ ብ fallback ዝተዳለወ ምኽሪ እዩ። ቅድሚ ናይ ስራሕ ውሳነ ናይ ከባቢ ምርግጋጽ የድሊ።",
            "sms": f"ምትሕስሳብ: {main_area} ኣብ {lead} ሓደጋ {hazard} ኣሎ። ማይ ቆጥቡ፣ ኩነታት ከባቢ ኣመልክቱ፣ መምርሒ ባለስልጣን ስዓቡ።",
        }
    if code == "so":
        return {
            "title": "Fasiraadda Khariidadda AI iyo Talo Hawleed",
            "executive_summary": f"Saadaasha {lead} waxay muujinaysaa khatar {hazard} oo ka jirta agagaarka {main_area}. Xaqiijin maxalli ah ayaa loo baahan yahay ka hor inta aan talo dadweyne la hawlgelin.",
            "spatial": ["Goobaha khatarta sare leh waxaa lagu aqoonsaday iyadoo lagu salaynayo darajada maamulka ee la bixiyay.", "Mudnaanta waa in la siiyaa meelaha ay isku darsamaan suurtagalnimada khatarta, nuglaanta iyo soo-gaadhistu."],
            "climate": ["SPI, leexashada roobka, boqolleyda roobka, CDD iyo CWD waa in si wadajir ah loo eego.", "CDD sare iyo roob ka hooseeya caadiga waxay muujin karaan walaac abaar ama qalayl."],
            "impact": ["Beeraha roobka ku tiirsan waxaa saameyn kara yaraanta qoyaanka ciidda.", "Bulshooyinka xoolo-dhaqatada iyo beeraleyda-xoolo-dhaqatada ah waxaa ku iman kara cadaadis biyo iyo daaq."],
            "farmer": ["Kaydi oo ilaali biyaha la heli karo.", "La jaanqaad wakhtiga beerista iyadoo lagu salaynayo bilowga roobka.", "La soco xaaladda daaqa, dalagga iyo xoolaha.", "U soo sheeg saameynta muuqata maamulka deegaanka."],
            "policy": ["Xaqiiji xaaladda degmooyinka khatarta sare leh 24-72 saacadood gudahood.", "Isku dubbarid xafiisyada beeraha, xoolaha, biyaha iyo maaraynta masiibooyinka.", "Diyaari farriimo digniin ah oo luqadda deegaanka ku qoran.", "Isticmaal warbixinnada bulshada si loo cusbooneysiiyo ficillada."],
            "human": ["Mudnaan sii kormeerka ilaha biyaha, taageerada xoolaha iyo daaqa.", "Kheyraadka u sii diyaari meelaha nuglaanta iyo soo-gaadhistu sareyso.", "Xaqiiji saadaasha adigoo adeegsanaya warbixinno goobta ka yimid."],
            "confidence": "Tani waa talo fallback ah. Xaqiijin maxalli ah ayaa muhiim ah ka hor go'aan hawlgal.",
            "sms": f"DIGNIIN: {main_area}. Khatar {hazard} ayaa jirta {lead}. Ilaali biyaha, la soco xaaladda deegaanka, raacna talada maamulka deegaanka.",
        }
    if code == "am":
        return {
            "title": "የAI ካርታ ትርጓሜና የተግባር ምክር",
            "executive_summary": f"የ{lead} ትንበያ በ{main_area} አካባቢ የ{hazard} አደጋ ምልክት እንዳለ ያሳያል። የሕዝብ ምክር ከመስጠት በፊት የመሬት ላይ ማረጋገጫ ያስፈልጋል።",
            "spatial": ["ከፍተኛ አደጋ ያላቸው ቦታዎች በተሰጠው የአስተዳደር ደረጃ ዝርዝር መሠረት ተለይተዋል።", "የአደጋ ዕድል፣ ተጋላጭነት እና ተጎጂነት በአንድ ላይ ሲጨምሩ ቅድሚያ ሊሰጥ ይገባል።"],
            "climate": ["SPI፣ የዝናብ ልዩነት፣ የዝናብ percentile፣ CDD እና CWD በአንድ ላይ መተንተን አለባቸው።", "ከፍተኛ CDD እና ዝቅተኛ ዝናብ የድርቅ ስጋት ሊያመለክቱ ይችላሉ።"],
            "impact": ["በዝናብ ላይ የሚመረኮዝ ግብርና የእርጥበት ጭንቀት ሊያጋጥመው ይችላል።", "አርብቶ አደር እና አግሮ-ፓስቶራል ማህበረሰቦች በውሃ እና በግጦሽ ላይ ጫና ሊያዩ ይችላሉ።"],
            "farmer": ["የሚገኘውን ውሃ ይቆጥቡ እና የውሃ ማከማቻን ያጠናክሩ።", "የመዝራት ጊዜን ከዝናብ መጀመሪያ ጋር ያስተካክሉ።", "የሰብል፣ የግጦሽ እና የእንስሳት ሁኔታን ይከታተሉ።", "የሚታዩ ተፅዕኖዎችን ለአካባቢ ባለሥልጣን ያሳውቁ።"],
            "policy": ["በከፍተኛ አደጋ ያሉ ወረዳዎችን በ24-72 ሰዓት ውስጥ ያረጋግጡ።", "የግብርና፣ የእንስሳት፣ የውሃ እና DRM ቢሮዎችን ያስተባብሩ።", "በአካባቢ ቋንቋ የማስጠንቀቂያ መልዕክቶችን ያዘጋጁ።", "የማህበረሰብ ሪፖርቶችን በመጠቀም እርምጃዎችን ያዘምኑ።"],
            "human": ["የውሃ ነጥቦችን፣ የእንስሳት ድጋፍን እና ግጦሽን ቅድሚያ ይስጡ።", "ሀብቶችን ከፍተኛ ተጋላጭነት እና ተጎጂነት ወዳላቸው ቦታዎች ያቅርቡ።", "ውሳኔዎችን በመሬት ላይ ማረጋገጫ ይደግፉ።"],
            "confidence": "ይህ የfallback ምክር ነው። ከኦፕሬሽን ውሳኔ በፊት የአካባቢ ማረጋገጫ ያስፈልጋል።",
            "sms": f"ማስጠንቀቂያ: {main_area} በ{lead} የ{hazard} አደጋ አለ። ውሃ ይቆጥቡ፣ ሁኔታውን ይከታተሉ፣ የአካባቢ መመሪያን ይከተሉ።",
        }
    return {}


def fallback_report(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]], error_message: Optional[str] = None) -> Dict[str, Any]:
    areas = request.top_admin_areas or []
    top_areas = areas[:5]
    code = get_request_language_code(request)
    label = get_request_language_label(request)

    if top_areas:
        first = top_areas[0]
        hazard = title_case(first.get("hazard") or request.map_context.hazard_type or "climate hazard")
        risk_level = title_case(first.get("risk_level") or "elevated")
        main_area = get_area_location(first)
    else:
        hazard = title_case(request.map_context.hazard_type or "climate hazard")
        risk_level = "Elevated"
        main_area = request.admin_selection.woredaLabel or request.admin_selection.zoneLabel or request.admin_selection.regionLabel or "the selected area"

    localized = localized_fallback_text(code, main_area, hazard, title_case(request.forecast_selection.lead))
    if localized:
        return {
            "title": localized["title"],
            "target_language": label,
            "executive_summary": localized["executive_summary"],
            "spatial_interpretation": localized["spatial"],
            "highest_risk_areas": [
                f"{get_area_location(item)}: {title_case(item.get('risk_level'))}; risk score {format_number(item.get('risk_score'))}; hazard probability {format_number(item.get('hazard_probability'))}."
                for item in top_areas
            ] or localized["spatial"],
            "climate_indicator_interpretation": localized["climate"],
            "cross_layer_insights": localized["spatial"],
            "impact_assessment": localized["impact"],
            "farmer_advisory": localized["farmer"],
            "policy_recommendations": localized["policy"],
            "humanitarian_priorities": localized["human"],
            "confidence_note": localized["confidence"],
            "sms_summary": localized["sms"],
            "_metadata": {
                "ai_engine": "rule_based_fallback_localized",
                "model": None,
                "used_screenshot": bool(request.map_image_base64),
                "target_language": label,
                "target_language_code": code,
                "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
                "error": error_message,
            },
        }

    highest_risk_areas = []
    for item in top_areas:
        highest_risk_areas.append(
            f"{get_area_location(item)}: {title_case(item.get('risk_level'))} {title_case(item.get('hazard'))} signal; risk score {format_number(item.get('risk_score'))}, hazard probability {format_number(item.get('hazard_probability'))}, exposure {format_number(item.get('exposure'))}, vulnerability {format_number(item.get('vulnerability'))}."
        )
    if not highest_risk_areas:
        highest_risk_areas = ["No administrative ranking was provided. Generate the ranking first to identify specific high-risk areas."]

    layer = title_case(request.forecast_selection.layer)
    indicator = title_case(request.forecast_selection.indicator)
    lead = title_case(request.forecast_selection.lead)
    scale = title_case(request.forecast_selection.forecastScale)
    return {
        "title": "AI Map Interpretation & Advisory",
        "target_language": label,
        "executive_summary": f"The {scale} {lead} forecast indicates {risk_level.lower()} {hazard.lower()} risk around {main_area}. The active dashboard layer is {layer}, and the active climate indicator is {indicator}.",
        "spatial_interpretation": ["The highest-risk signal is concentrated around the provided top-ranked administrative areas.", "Risk should be interpreted jointly from hazard probability, risk score, exposure, and vulnerability layers."],
        "highest_risk_areas": highest_risk_areas,
        "climate_indicator_interpretation": ["SPI, rainfall anomaly, rainfall percentile, CDD, and CWD should be reviewed together.", "Low SPI, negative rainfall anomaly, low rainfall percentile, and high CDD values generally indicate dry-spell or drought concern."],
        "cross_layer_insights": ["The strongest concern is where climate hazard signals overlap with high exposure and high vulnerability.", "Use all-layer summaries to separate hazard-driven risk from vulnerability-driven risk."],
        "impact_assessment": ["Rainfed agriculture may face moisture stress where dry conditions persist.", "Agro-pastoral communities may experience pasture and water stress if forecast dryness is confirmed locally."],
        "farmer_advisory": ["Conserve available water and strengthen household or farm-level water storage.", "Adjust planting timing where rainfall onset is uncertain.", "Monitor pasture, crop stress, and livestock body condition.", "Report emerging impacts to local authorities."],
        "policy_recommendations": ["Verify conditions in the highest-risk woredas within 24-72 hours.", "Coordinate agriculture, livestock, water, health, and DRM offices.", "Prepare targeted advisories using local language and local impact information.", "Use community reports to update the action tracker."],
        "humanitarian_priorities": ["Prioritize water-point monitoring and livestock support in high-risk areas.", "Pre-position resources where hazard probability, exposure, and vulnerability are jointly high.", "Use field reports to confirm whether forecast risk is becoming observed impact."],
        "confidence_note": "This advisory was generated by the rule-based fallback because the OpenAI call was unavailable. Use field verification before operational decisions.",
        "sms_summary": f"EARLY WARNING: {main_area}. {risk_level} {hazard} risk for {lead}. Monitor local conditions and follow local authority guidance.",
        "_metadata": {"ai_engine": "rule_based_fallback", "model": None, "used_screenshot": bool(request.map_image_base64), "target_language": label, "target_language_code": code, "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance], "error": error_message},
    }


def parse_json_from_text(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
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


def call_openai_model(request: AIMapInterpretationRequest, retrieved_guidance: List[Dict[str, str]]) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("OpenAI Python package is not installed. Run: pip install openai") from exc

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MAP_AI_MODEL", DEFAULT_MODEL)
    code = get_request_language_code(request)
    label = get_request_language_label(request)

    system_prompt = build_system_prompt(request)
    user_prompt = build_user_prompt(request, retrieved_guidance)
    image_url = normalize_data_url(request.map_image_base64) if request.use_screenshot else None

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
            max_output_tokens=3000,
        )
        report = parse_json_from_text(response.output_text)
        report["target_language"] = label
        report["_metadata"] = {
            "ai_engine": "openai_responses_api",
            "model": model,
            "used_screenshot": bool(image_url),
            "target_language": label,
            "target_language_code": code,
            "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
        }
        return report
    except Exception as structured_error:
        fallback_content: List[Dict[str, Any]] = [
            {
                "type": "input_text",
                "text": (
                    f"{system_prompt}\n\n{user_prompt}\n\n"
                    f"FINAL LANGUAGE REMINDER: {language_instruction(code)}\n"
                    "Return ONLY valid JSON with these keys: title, target_language, executive_summary, "
                    "spatial_interpretation, highest_risk_areas, climate_indicator_interpretation, "
                    "cross_layer_insights, impact_assessment, farmer_advisory, policy_recommendations, "
                    "humanitarian_priorities, confidence_note, sms_summary."
                ),
            }
        ]
        if image_url:
            fallback_content.append({"type": "input_image", "image_url": image_url, "detail": "low"})
        response = client.responses.create(model=model, input=[{"role": "user", "content": fallback_content}], max_output_tokens=3000)
        report = parse_json_from_text(response.output_text)
        report["target_language"] = label
        report["_metadata"] = {
            "ai_engine": "openai_responses_api_json_fallback",
            "model": model,
            "used_screenshot": bool(image_url),
            "target_language": label,
            "target_language_code": code,
            "retrieved_guidance_titles": [item["title"] for item in retrieved_guidance],
            "structured_output_error": str(structured_error),
        }
        return report


@router.post("/map-interpretation")
async def generate_ai_map_interpretation(request: AIMapInterpretationRequest) -> Dict[str, Any]:
    # Normalize language fields in the request object so downstream prompt, cache metadata,
    # fallback, and report metadata are consistent for om/ti/so/am/en.
    code = get_request_language_code(request)
    request.target_language = code
    request.target_language_label = LANGUAGE_LABELS.get(code, "English")

    retrieved_guidance = retrieve_guidance(request)
    try:
        return call_openai_model(request, retrieved_guidance)
    except Exception as error:
        return fallback_report(request=request, retrieved_guidance=retrieved_guidance, error_message=str(error))
