// Language-fix notes for AIMapInterpretation.jsx
// Apply these edits to your existing frontend/src/components/AIMapInterpretation.jsx.

// 1) Change the import line:
import { useEffect, useMemo, useState } from "react";

// 2) Add/replace these language helper constants/functions near the top:
const LANGUAGE_ALIASES = {
  en: { code: "en", label: "English" },
  eng: { code: "en", label: "English" },
  english: { code: "en", label: "English" },
  am: { code: "am", label: "Amharic" },
  amh: { code: "am", label: "Amharic" },
  amharic: { code: "am", label: "Amharic" },
  "am-et": { code: "am", label: "Amharic" },
  "አማርኛ": { code: "am", label: "Amharic" },
  so: { code: "so", label: "Somali" },
  somali: { code: "so", label: "Somali" },
  sw: { code: "sw", label: "Swahili" },
  swahili: { code: "sw", label: "Swahili" },
  om: { code: "om", label: "Afaan Oromo" },
  oromo: { code: "om", label: "Afaan Oromo" },
};

function normalizeLanguage(value) {
  const key = String(value || "en").trim().toLowerCase().replaceAll("_", "-");
  return LANGUAGE_ALIASES[key] || { code: key || "en", label: titleCase(value || "English") };
}

// 3) Inside the AIMapInterpretation function, after useState declarations, add:
const normalizedLanguage = useMemo(() => normalizeLanguage(selectedLanguage), [selectedLanguage]);

// 4) In buildCacheKey call, use normalizedLanguage.code instead of selectedLanguage:
const cacheKey = useMemo(() => {
  return buildCacheKey({
    forecastSelection,
    adminSelection,
    selectedLanguage: normalizedLanguage.code,
    useScreenshot,
  });
}, [forecastSelection, adminSelection, normalizedLanguage.code, useScreenshot]);

// 5) Add this effect inside the component so an old English report is not kept on screen after language changes:
useEffect(() => {
  const cached = getCachedReport(cacheKey);
  setReport(cached);
  setStatusMessage(
    cached
      ? `Loaded saved ${normalizedLanguage.label} advisory from browser cache. No new OpenAI API call was made.`
      : ""
  );
}, [cacheKey, normalizedLanguage.label]);

// 6) In contextSummary, set language from normalizedLanguage:
language: normalizedLanguage.label,

// 7) In the payload sent to /api/ai/map-interpretation, replace the language fields with:
target_language: normalizedLanguage.code,
target_language_label: normalizedLanguage.label,

// 8) When showing output language, use:
<strong>{normalizedLanguage.label}</strong>
