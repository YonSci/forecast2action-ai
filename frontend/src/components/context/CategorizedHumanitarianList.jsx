// Renders humanitarian_priorities (see app/api/report_stages.py::
// build_stage3_prompt) -- structured by category (monitoring/preparedness/
// pre_positioning/immediate_action) instead of a flat bullet list, per
// step 7 item 7. Tolerates the old flat-array shape too (e.g. a stale
// cached report from before this change) by falling back to a single
// unlabeled section. Collapsed by default, same as TimescaledAdvisoryList.
//
// Each bullet is now itself a real structured object (area/action/
// trigger/evidence/confidence -- see _ADVISORY_ITEM_SCHEMA in
// app/api/ai_map_interpretation.py) -- see TimescaledAdvisoryList's
// AdvisoryBullet for the same rendering, reused here.

import { useState } from "react";
import AdvisoryBullet from "./AdvisoryBullet.jsx";

const CATEGORY_LABELS = {
  monitoring: "Monitoring",
  preparedness: "Preparedness",
  pre_positioning: "Pre-positioning",
  immediate_action: "Immediate action",
};

function countItems(priorities) {
  if (Array.isArray(priorities)) {
    return priorities.length;
  }
  return Object.values(priorities).reduce(
    (total, items) => total + (Array.isArray(items) ? items.length : 0),
    0,
  );
}

function CategorizedHumanitarianList({ priorities, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);

  if (!priorities) {
    return null;
  }

  const isFlat = Array.isArray(priorities);
  const categories = isFlat
    ? []
    : Object.keys(CATEGORY_LABELS).filter(
        (key) => Array.isArray(priorities[key]) && priorities[key].length > 0,
      );

  if (isFlat ? priorities.length === 0 : categories.length === 0) {
    return null;
  }

  const itemCount = countItems(priorities);

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
        Humanitarian priorities
        <span className="ai-priority-col-count">{itemCount} item{itemCount === 1 ? "" : "s"}</span>
      </h4>
      <div className={`ai-collapsible-body${open ? " open" : ""}`}>
        <div>
          {isFlat ? (
            <ul>
              {priorities.map((item, index) => (
                <AdvisoryBullet item={item} key={index} />
              ))}
            </ul>
          ) : (
            <div className="ai-cat-grid">
              {categories.map((key) => (
                <div key={key} className="ai-timescale-block">
                  <span className="ai-timescale-label">{CATEGORY_LABELS[key]}</span>
                  <ul>
                    {priorities[key].map((item, index) => (
                      <AdvisoryBullet item={item} key={index} />
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default CategorizedHumanitarianList;
