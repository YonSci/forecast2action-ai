// Dashboard.jsx patch for language-aware AI advisory

// 1. Add this import:
import AIMapInterpretation from "../components/AIMapInterpretation.jsx";

// 2. Put this immediately after ForecastLayerMap.
//    The important new prop is selectedLanguage={selectedLanguage}.

<ForecastLayerMap
  adminSelection={adminSelection}
  onForecastSelectionChange={setForecastSelection}
/>

<AIMapInterpretation
  forecastSelection={forecastSelection}
  adminSelection={adminSelection}
  selectedPriorityArea={selectedPriorityArea}
  selectedLanguage={selectedLanguage}
/>
