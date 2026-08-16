import { Link } from "react-router-dom";
import "../styles/landing.css";

function SubPageLayout({ children }) {
  return (
    <div className="lp-root">
      <div className="lp-bg-field" />

      <nav className="lp-nav">
        <div className="lp-wrap lp-nav-row">
          <Link to="/" className="lp-brand">
            <svg
              className="lp-brand-mark"
              viewBox="0 0 32 32"
              fill="none"
              aria-hidden="true"
            >
              <circle
                cx="16"
                cy="16"
                r="14.5"
                stroke="#35d4c7"
                strokeWidth="1.4"
                opacity="0.5"
              />
              <path
                d="M16 3v6M16 23v6M3 16h6M23 16h6"
                stroke="#35d4c7"
                strokeWidth="1.4"
                opacity="0.5"
              />
              <circle cx="16" cy="16" r="6.5" fill="#35d4c7" opacity="0.16" />
              <circle
                cx="16"
                cy="16"
                r="6.5"
                stroke="#35d4c7"
                strokeWidth="1.6"
              />
              <circle cx="20" cy="12" r="2.4" fill="#f79009" />
            </svg>
            Forecast2Action <span style={{ color: "#35d4c7" }}>AI</span>
          </Link>
          <div className="lp-nav-links">
            <Link to="/platform">Platform</Link>
            <Link to="/how-it-works">How it works</Link>
            <Link to="/data-sources">Data sources</Link>
            <Link to="/docs">Docs</Link>
            <Link to="/track-record">Track record</Link>
            <Link to="/about">About</Link>
          </div>
          <Link to="/dashboard" className="lp-btn lp-btn-ghost lp-btn-small">
            Launch Dashboard
          </Link>
        </div>
      </nav>

      <main>{children}</main>

      <div className="lp-ribbon">
        {/* <span className="lp-ribbon-tag">An ILRI product</span> */}
        <p>
          "Reimagining the future of early warning and early action for safer,
          more resilient communities across the region."
        </p>
      </div>

      <footer className="lp-footer">
        <div className="lp-wrap lp-footer-row">
          <Link to="/" className="lp-brand">
            <svg
              className="lp-brand-mark"
              viewBox="0 0 32 32"
              fill="none"
              aria-hidden="true"
              style={{ width: "22px", height: "22px" }}
            >
              <circle
                cx="16"
                cy="16"
                r="14.5"
                stroke="#35d4c7"
                strokeWidth="1.4"
                opacity="0.5"
              />
              <circle cx="16" cy="16" r="6.5" fill="#35d4c7" opacity="0.16" />
              <circle
                cx="16"
                cy="16"
                r="6.5"
                stroke="#35d4c7"
                strokeWidth="1.6"
              />
            </svg>
            Forecast2Action AI
          </Link>
          <Link to="/contact" className="lp-footer-contact-link">
            Contact us
          </Link>
          <span className="lp-footer-meta">
            CLIMATE RISK &amp; EARLY WARNING SYSTEMS FOR EAST AFRICA
          </span>
        </div>
      </footer>
    </div>
  );
}

export default SubPageLayout;
