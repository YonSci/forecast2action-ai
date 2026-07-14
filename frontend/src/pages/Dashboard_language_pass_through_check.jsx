// Dashboard.jsx language pass-through check

// Make sure this import exists:
import AIMapInterpretation from "../components/AIMapInterpretation.jsx";

// Make sure selectedLanguage state exists in Dashboard.jsx:
const [selectedLanguage, setSelectedLanguage] = useState("en");

// Make sure AdminBoundarySelector receives these props:
<AdminBoundarySelector
  selectedLanguage={selectedLanguage}
  onLanguageChange={setSelectedLanguage}
  onSelectionChange={setAdminSelection}
  onClearPrioritySelection={handleClearPrioritySelection}
/>

// Make sure AIMapInterpretation receives selectedLanguage:
<AIMapInterpretation
  forecastSelection={forecastSelection}
  adminSelection={adminSelection}
  selectedPriorityArea={selectedPriorityArea}
  selectedLanguage={selectedLanguage}
/>
