import { useEffect, useState } from "react";

export type CopilotCandidate = {
  claim_id: number;
  version_id: number;
  company: string;
  document_id: number;
  document_name: string;
  page_number: number;
  claim_text: string;
  greenwashing_type: "Type 1" | "Type 2" | "Type 3" | "Type 4" | string;
  justification: string;
  boxes?: number[][][];
  evidence_quote?: string;
  status: string;
};

type CopilotResponse = {
  status: string;
  candidates: CopilotCandidate[];
  count: number;
};

async function fetchCandidates(): Promise<CopilotResponse> {
  const r = await fetch("/api/copilot/candidates", { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as CopilotResponse;
}

export function CopilotDrawer({
  open,
  onClose,
  onSelectCandidate,
  onFlagCandidate,
}: {
  open: boolean;
  onClose: () => void;
  onSelectCandidate: (c: CopilotCandidate) => void;
  onFlagCandidate: (c: CopilotCandidate) => void;
}) {
  const [candidates, setCandidates] = useState<CopilotCandidate[]>([]);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    fetchCandidates()
      .then((data) => {
        setLoading(false);
        if (data.candidates) {
          setCandidates(data.candidates);
        } else {
          setError("Failed to load auditor copilot candidates.");
        }
      })
      .catch((e: unknown) => {
        setLoading(false);
        setError(String(e));
      });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const activeCandidates = candidates.filter((c) => !dismissed.has(c.claim_id));

  return (
    <>
    <div className="copilot-backdrop" onClick={onClose} aria-hidden="true" />
    <aside className="copilot-drawer" aria-label="Auditor Copilot Proposals">
      <div className="copilot-header">
        <div className="copilot-title">
          <h3>Auditor Copilot Proposals</h3>
          <span className="copilot-badge">{activeCandidates.length} unreviewed</span>
        </div>
        <button type="button" className="close-btn" onClick={onClose} aria-label="Close copilot drawer">
          Close
        </button>
      </div>

      <p className="copilot-notice">
        <strong>Proposals, not findings.</strong> These candidates come from the EmeraldMind taxonomy. A human auditor has to verify
        each one before it is recorded on the ledger.
      </p>

      {loading && <p className="hint">Scanning the claims against their evidence.</p>}
      {error && <p className="problem">{error}</p>}

      {!loading && activeCandidates.length === 0 && (
        <div className="empty-state">
          <p>No greenwashing candidates surfaced.</p>
          <span className="meta">
            None of the available disclosures has a claim the taxonomy flags.
          </span>
        </div>
      )}

      <ul className="candidate-list">
        {activeCandidates.map((c) => (
          <li key={c.claim_id} className="candidate-card">
            <div className="card-top">
              <span className="card-company">{c.company}</span>
              <span className="card-loc">
                {c.document_name} · Page {c.page_number}
              </span>
            </div>

            <div className="taxonomy-pill">
              {c.greenwashing_type}
            </div>

            <blockquote className="claim-quote">"{c.claim_text}"</blockquote>

            <p className="justification-text">
              <strong>Audit Justification:</strong> {c.justification}
            </p>

            <div className="card-actions">
              <button
                type="button"
                className="action-btn jump-btn"
                onClick={() => onSelectCandidate(c)}
              >
                Inspect Page {c.page_number}
              </button>
              <button
                type="button"
                className="action-btn flag-btn"
                onClick={() => onFlagCandidate(c)}
              >
                Review & Flag
              </button>
              <button
                type="button"
                className="action-btn dismiss-btn"
                onClick={() => setDismissed((prev) => new Set([...prev, c.claim_id]))}
              >
                Dismiss
              </button>
            </div>
          </li>
        ))}
      </ul>
    </aside>
    </>
  );
}
