// Dashboard.jsx: keep your existing Dashboard.jsx, but ensure these two parts exist.

// 1. Import:
import AIMapInterpretation from "../components/AIMapInterpretation.jsx";

// 2. Place immediately after ForecastLayerMap and make sure selectedLanguage is passed:
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
