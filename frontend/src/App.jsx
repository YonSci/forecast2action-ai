import { BrowserRouter, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import Landing from "./pages/Landing.jsx";
import Platform from "./pages/Platform.jsx";
import HowItWorks from "./pages/HowItWorks.jsx";
import DataSources from "./pages/DataSources.jsx";
import About from "./pages/About.jsx";
import TechnicalDocumentation from "./pages/TechnicalDocumentation.jsx";
import TrackRecord from "./pages/TrackRecord.jsx";
import Contact from "./pages/Contact.jsx";
import "./styles/main.css";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/platform" element={<Platform />} />
        <Route path="/how-it-works" element={<HowItWorks />} />
        <Route path="/data-sources" element={<DataSources />} />
        <Route path="/about" element={<About />} />
        <Route path="/docs" element={<TechnicalDocumentation />} />
        <Route path="/track-record" element={<TrackRecord />} />
        <Route path="/contact" element={<Contact />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
