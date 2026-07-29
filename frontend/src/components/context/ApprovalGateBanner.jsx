// Shown per-task in ActionImplementationTracker.jsx when a context-driven
// task's approval_status is "Pending" (i.e. the Decision Policy marked its
// action_category as approval_required -- see
// app/decision/policy_engine.py's action_categories). Approve/Reject calls
// PATCH /api/action-tracker/approval, which the LLM never has access to:
// this is a deliberately human-only gate.
function ApprovalGateBanner({ approvalStatus, onApprove, onReject }) {
  if (!approvalStatus || approvalStatus === "Not required") {
    return null;
  }

  if (approvalStatus === "Approved" || approvalStatus === "Rejected") {
    return (
      <span className={`approval-status-pill approval-${approvalStatus.toLowerCase()}`}>
        {approvalStatus}
      </span>
    );
  }

  return (
    <div className="approval-gate-banner">
      <span className="approval-status-pill approval-pending">Approval pending</span>
      <button type="button" className="table-link-button" onClick={onApprove}>
        Approve
      </button>
      <button type="button" className="table-link-button" onClick={onReject}>
        Reject
      </button>
    </div>
  );
}

export default ApprovalGateBanner;
