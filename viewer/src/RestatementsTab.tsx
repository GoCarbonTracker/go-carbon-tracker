import { useEffect, useState } from "react";
import type { EvidenceTarget } from "./records.ts";

export type RestatementPair = {
  series_id: string;
  company: string;
  metric_key: string | null;
  label: string;
  reporting_boundary: string;
  period_start: string;
  period_end: string;
  state: "same value" | "restatement" | "unresolved conflict" | "not compared" | string;
  reason: string | null;
  a: {
    claim_id: number;
    claim_version_id: number;
    document_id: number;
    document_name?: string;
    page_number: number;
    number: number | null;
    value_text: string;
    unit?: string;
    value_base?: number;
  };
  b: {
    claim_id: number;
    claim_version_id: number;
    document_id: number;
    document_name?: string;
    page_number: number;
    number: number | null;
    value_text: string;
    unit?: string;
    value_base?: number;
  };
};

type RestateResponse = {
  status: string;
  pairs: RestatementPair[];
  hidden: number;
  count: number;
};

async function fetchPairs(): Promise<RestateResponse> {
  const r = await fetch("/api/restate/pairs", { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as RestateResponse;
}

export function RestatementsTab({
  openEvidence,
}: {
  openEvidence: (target: EvidenceTarget) => void;
}) {
  const [pairs, setPairs] = useState<RestatementPair[]>([]);
  const [filterState, setFilterState] = useState<string>("all");
  const [search, setSearch] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchPairs()
      .then((data) => {
        setLoading(false);
        if (data.pairs) {
          setPairs(data.pairs);
        } else {
          setError("Failed to load restatement comparisons.");
        }
      })
      .catch((e: unknown) => {
        setLoading(false);
        setError(String(e));
      });
  }, []);

  const stateClass = (st: string) => {
    switch (st) {
      case "same value":
        return "state-pill state-same";
      case "restatement":
        return "state-pill state-restated";
      case "unresolved conflict":
        return "state-pill state-conflict";
      default:
        return "state-pill state-notcompared";
    }
  };

  const filtered = pairs.filter((p) => {
    if (filterState !== "all" && p.state !== filterState) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      const matchLabel = p.label.toLowerCase().includes(q);
      const matchComp = p.company.toLowerCase().includes(q);
      const matchKey = p.metric_key?.toLowerCase().includes(q) ?? false;
      if (!matchLabel && !matchComp && !matchKey) return false;
    }
    return true;
  });

  return (
    <div className="restate-tab" aria-label="Restatements Matrix">
      <div className="restate-toolbar">
        <div className="state-filters" role="group" aria-label="Filter by state">
          {[
            ["all", `All (${pairs.length})`],
            ["same value", `Corroborated (${pairs.filter((p) => p.state === "same value").length})`],
            ["restatement", `Restatements (${pairs.filter((p) => p.state === "restatement").length})`],
            ["unresolved conflict", `Conflicts (${pairs.filter((p) => p.state === "unresolved conflict").length})`],
            ["not compared", `Not Compared (${pairs.filter((p) => p.state === "not compared").length})`],
          ].map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={filterState === key ? "filter-pill active" : "filter-pill"}
              onClick={() => setFilterState(key)}
            >
              {label}
            </button>
          ))}
        </div>

        <input
          type="search"
          className="restate-search"
          placeholder="Filter metrics (e.g. scope 1, china)..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading && <p className="hint">Comparing cross-report figures across disclosure cycles...</p>}
      {error && <p className="problem">{error}</p>}

      {!loading && filtered.length === 0 && (
        <p className="hint">No restatement pairs match the selected state.</p>
      )}

      {!loading && filtered.length > 0 && (
        <table className="restate-table">
          <caption>Cross-Report Harmonization & Restatement Reconciliation ({filtered.length} pairs)</caption>
          <thead>
            <tr>
              <th scope="col">Company</th>
              <th scope="col">Metric</th>
              <th scope="col">Reporting Period</th>
              <th scope="col">Boundary</th>
              <th scope="col" className="num">Disclosure A</th>
              <th scope="col" className="num">Disclosure B</th>
              <th scope="col">Reconciliation State</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 250).map((p, idx) => (
              <tr key={idx} className="restate-row">
                <td className="company-col">{p.company}</td>
                <td className="metric-col" title={p.label}>
                  <div className="clamp">{p.label}</div>
                  {p.metric_key && <span className="meta">{p.metric_key}</span>}
                </td>
                <td className="period-col">
                  {p.period_start} · {p.period_end}
                </td>
                <td className="boundary-col">{p.reporting_boundary}</td>
                <td className="num">
                  <button
                    type="button"
                    className="link-val"
                    onClick={() =>
                      openEvidence({
                        document: p.a.document_id,
                        page: p.a.page_number,
                        claim_id: p.a.claim_id,
                      })
                    }
                  >
                    {p.a.value_text} <span className="meta">p{p.a.page_number}</span>
                  </button>
                </td>
                <td className="num">
                  <button
                    type="button"
                    className="link-val"
                    onClick={() =>
                      openEvidence({
                        document: p.b.document_id,
                        page: p.b.page_number,
                        claim_id: p.b.claim_id,
                      })
                    }
                  >
                    {p.b.value_text} <span className="meta">p{p.b.page_number}</span>
                  </button>
                </td>
                <td>
                  <span className={stateClass(p.state)}>{p.state}</span>
                  {p.reason && <span className="reason-text">({p.reason})</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
