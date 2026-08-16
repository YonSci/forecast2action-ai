import { Link } from "react-router-dom";
import SubPageLayout from "../components/SubPageLayout.jsx";

function HowItWorks() {
  return (
    <SubPageLayout>
      <section className="lp-article-hero">
        <div className="lp-wrap">
          <Link to="/" className="lp-back-link">
            ← Back to home
          </Link>
          <span className="lp-eyebrow">
            <span className="lp-dot" /> How it works
          </span>
          <h1>From raw forecast grid to a message someone can act on</h1>
          <p className="lp-hero-sub">
            Four stages, each one deterministic and inspectable before the next
            begins so by the time an AI model writes a single word, every number
            in the report has already been computed, not guessed.
          </p>
        </div>
      </section>

      <section className="lp-article-section">
        <div className="lp-wrap">
          <div className="lp-pillar-list">
            <div className="lp-pillar-list-item">
              <span className="lp-pillar-list-num">01</span>
              <div>
                <h3>Ingest forecast data</h3>
                <p>
                  A 25-member seasonal ensemble (ECMWF SEAS5) and CHIRPS
                  observational rainfall are pulled in at 0.25° resolution,
                  alongside exposure layers (population, cropland, livestock,
                  roads, health facilities) and vulnerability layers (wealth,
                  aridity, irrigation access, electrification, terrain, soil,
                  and river proximity) all resampled to the same analysis grid
                  so every layer lines up cell for cell.
                </p>
              </div>
            </div>

            <div className="lp-pillar-list-item">
              <span className="lp-pillar-list-num">02</span>
              <div>
                <h3>Compute hazard indices</h3>
                <p>
                  Seven climate indicators (SPI, rainfall percentile, CDD, CWD,
                  Rx1day, Rx5day, rainfall total) are each standardized into a
                  0–1 score and combined into a per-realization hazard index.
                  That index is preserved across every ensemble member never
                  collapsed to a single number too early so probability and
                  severity can be measured separately before being recombined
                  into the final hazard term.
                </p>
              </div>
            </div>

            <div className="lp-pillar-list-item">
              <span className="lp-pillar-list-num">03</span>
              <div>
                <h3>Rank &amp; classify</h3>
                <p>
                  Hazard is multiplied through real exposure and vulnerability
                  layers to produce a 0–100 risk score per area, then classified
                  into Trigger / Warning / Watch / No alert bands. Regions are
                  ranked by a deterministic priority formula the same ranking a
                  responder sees in the table is the same one driving the map
                  and the generated advisory.
                </p>
              </div>
            </div>

            <div className="lp-pillar-list-item">
              <span className="lp-pillar-list-num">04</span>
              <div>
                <h3>Deliver the advisory</h3>
                <p>
                  A staged AI pipeline turns the ranked evidence into farmer,
                  agro-pastoral, and humanitarian advisories, cross-checked
                  against the same evidence it was given before being delivered
                  as an SMS, a WhatsApp message, or the full dashboard report.
                  From there, recommended actions can be tracked to
                  implementation, a follow-up question can go to the grounded
                  dashboard chat assistant, and the whole advisory can be
                  exported as a self-contained HTML bulletin with every
                  climate-indicator, risk-layer, and priority-area map
                  included.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <hr className="lp-article-divider" />

      <section className="lp-article-section">
        <div className="lp-wrap">
          <h2>Why the order matters</h2>
          <div className="lp-prose">
            <p>
              Each stage only receives what the previous one already validated.
              The ranking engine never sees an AI-generated opinion, and the
              language model that writes the final advisory never sees raw
              ensemble data only the already-ranked, already-classified
              evidence. That separation is what makes it possible to catch a
              hallucinated place name or an invented statistic automatically,
              rather than trusting the model's output at face value.
            </p>
          </div>
        </div>
      </section>
    </SubPageLayout>
  );
}

export default HowItWorks;
