import { Link } from "react-router-dom";
import SubPageLayout from "../components/SubPageLayout.jsx";

const CONTACT_LINKS = [
  {
    label: "Email",
    value: "yonas.mersha14@gmail.com",
    href: "mailto:yonas.mersha14@gmail.com",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <path d="M4 7l8 6 8-6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    label: "Email (work)",
    value: "yonas@grace-resilience.com",
    href: "mailto:yonas@grace-resilience.com",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <path d="M4 7l8 6 8-6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    label: "GitHub",
    value: "github.com/YonSci",
    href: "https://github.com/YonSci",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M12 2a10 10 0 00-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.89 1.53 2.34 1.09 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.53 9.53 0 015 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0012 2z"
          fill="currentColor"
        />
      </svg>
    ),
  },
  {
    label: "LinkedIn",
    value: "linkedin.com/in/yonas-mersha-baab561b5",
    href: "https://linkedin.com/in/yonas-mersha-baab561b5",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="3" y="3" width="18" height="18" rx="3" stroke="currentColor" strokeWidth="1.6" />
        <path d="M7.5 10v6.5M7.5 7.5v.01M12 16.5V13c0-1.5 1-2.5 2.25-2.5S16.5 11.5 16.5 13v3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M12 10v6.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    label: "Project repository",
    value: "github.com/YonSci/forecast2action-ai",
    href: "https://github.com/YonSci/forecast2action-ai",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M4 4v11a2 2 0 002 2h4l3 3 3-3h2a2 2 0 002-2V4" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M8 9h8M8 12.5h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    label: "Live dashboard",
    value: "forecast2action-ai.vercel.app",
    href: "https://forecast2action-ai.vercel.app/",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.6" />
        <path d="M3 12h18M12 3c2.5 2.5 3.5 6 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-6-3.5-9s1-6.5 3.5-9z" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    ),
  },
];

function Contact() {
  return (
    <SubPageLayout>
      <section className="lp-article-hero">
        <div className="lp-wrap">
          <Link to="/" className="lp-back-link">
            ← Back to home
          </Link>
          <span className="lp-eyebrow">
            <span className="lp-dot" /> Contact
          </span>
          <h1>Get in touch</h1>
          <p className="lp-hero-sub">
            Questions about the methodology, the data, or the IGAD Hackathon
            2026 submission — reach out directly, or explore the project on
            GitHub.
          </p>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <div className="lp-contact-grid">
            {CONTACT_LINKS.map((item) => (
              <a
                key={item.label}
                href={item.href}
                target={item.href.startsWith("http") ? "_blank" : undefined}
                rel={item.href.startsWith("http") ? "noreferrer" : undefined}
                className="lp-contact-card"
              >
                <span className="lp-contact-icon">{item.icon}</span>
                <span>
                  <span className="lp-contact-label">{item.label}</span>
                  <span className="lp-contact-value">{item.value}</span>
                </span>
              </a>
            ))}
          </div>
        </div>
      </section>
    </SubPageLayout>
  );
}

export default Contact;
