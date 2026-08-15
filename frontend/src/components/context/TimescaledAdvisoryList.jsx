// Renders farmer_advisory / agro_pastoral_advisory (see
// app/api/report_stages.py::build_stage3_prompt) -- structured by
// timescale (immediate/near_term/preparedness) instead of a flat bullet
// list, per step 7 item 6. Tolerates the old flat-array shape too (e.g. a
// stale cached report from before this change) by falling back to a
// single unlabeled section. Collapsed by default so these longer sections
// don't dominate the page -- the user expands only the ones they need.
//
// Each bullet is now itself a real structured object (area/action/
// trigger/evidence/cross_indicator_confidence -- see _ADVISORY_ITEM_SCHEMA in
// app/api/ai_map_interpretation.py), not a bare string -- see
// AdvisoryBullet.jsx (shared with CategorizedHumanitarianList).

import { useState } from "react";
import AdvisoryBullet from "./AdvisoryBullet.jsx";

const TIMESCALE_LABELS = {
  immediate: "Immediate (next 7 days)",
  near_term: "Near-term (2-4 weeks)",
  preparedness: "Preparedness (remainder of forecast period)",
};

function countItems(advisory) {
  if (Array.isArray(advisory)) {
    return advisory.length;
  }
  return Object.values(advisory).reduce(
    (total, items) => total + (Array.isArray(items) ? items.length : 0),
    0,
  );
}

function TimescaledAdvisoryList({ title, advisory, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);

  if (!advisory) {
    return null;
  }

  const isFlat = Array.isArray(advisory);
  const timescales = isFlat
    ? []
    : Object.keys(TIMESCALE_LABELS).filter(
        (key) => Array.isArray(advisory[key]) && advisory[key].length > 0,
      );

  if (isFlat ? advisory.length === 0 : timescales.length === 0) {
    return null;
  }

  const itemCount = countItems(advisory);

  return (
    <div className="ai-report-section ai-timescaled-advisory">
      <h4
        className="ai-collapsible"
        onClick={() => setOpen((value) => !value)}
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setOpen((value) => !value);
          }
        }}
      >
        <span className={`ai-collapsible-chevron${open ? " open" : ""}`}>&#9656;</span>
        {title}
        <span className="ai-priority-col-count">{itemCount} item{itemCount === 1 ? "" : "s"}</span>
      </h4>
      <div className={`ai-collapsible-body${open ? " open" : ""}`}>
        <div>
          {isFlat ? (
            <ul>
              {advisory.map((item, index) => (
                <AdvisoryBullet item={item} key={index} />
              ))}
            </ul>
          ) : (
            timescales.map((key) => (
              <div key={key} className="ai-timescale-block">
                <span className="ai-timescale-label">{TIMESCALE_LABELS[key]}</span>
                <ul>
                  {advisory[key].map((item, index) => (
                    <AdvisoryBullet item={item} key={index} />
                  ))}
                </ul>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default TimescaledAdvisoryList;
