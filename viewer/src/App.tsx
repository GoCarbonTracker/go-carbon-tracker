import { Fragment, lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { ADJUDICATION_STATES, bandText, boundaryText, type Box, byPosition, correctionBody, correctionText, type CorrectionFields, decide, type Entry, evidenceTarget, flagText, hasRecords, highlightText, label, newestOnly, overlayShown, periodText, recordBody, restateCommand, reReviewText, SELF_DECLARED, stepClaim, stepPage, type Version, whoText, type Claim } from "./logic.ts";
import { availableText, countText, type EvidenceTarget, type Filter, isCell, isStale, newerVersion, periodUnknownText, recordsBody, type SeriesValue } from "./records.ts";
import { FilterBar } from "./FilterBar.tsx";
import { CellView } from "./CellView.tsx";
import { Tables } from "./Tables.tsx";
import { RestatementsTab } from "./RestatementsTab.tsx";
import { CopilotDrawer, type CopilotCandidate } from "./CopilotDrawer.tsx";
import { ChipLine, Transfer } from "./Transfer.tsx";
import { type SavedView, SavedViews } from "./SavedViews.tsx";
import { type Chosen, Questions } from "./Questions.tsx";
import type { Chip, Sent, Tab } from "./transfer.ts";
const Graphs = lazy(() => import("./Graphs.tsx")); // story 6.3; it imports Cytoscape only when the Graphs tab is shown

type Company = { id: number; name: string; documents: Doc[] };
type Doc = { id: number; logical_name: string; version: number; file_type: string };
// pdfplumber's page frame, the space of the stored boxes: it need not start at 0, 0.
type PageSize = { left: number; top: number; width: number; height: number };
type Opened = { id: number; name: string; pages: PageSize[] };
type Failure = { cause: string; next_action: string };

class ApiError extends Error {
  failure: Failure;
  status: number;
  constructor(failure: Failure, status = 0) {
    super(failure.cause);
    this.failure = failure;
    this.status = status;
  }
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  const data = await r.json();
  if (!r.ok) throw new ApiError(data, r.status);
  return data as T;
}

/** A Tables-and-Graphs read: the filter and the pinned version in a POST body (F3). */
async function records<T>(body: object): Promise<T> {
  const r = await fetch("/api/records", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new ApiError(data, r.status);
  return data as T;
}

type Count = { data_version: number; matched: number; excluded: { period_unknown: number }; empty: string | null;
  hidden_by_archive: { text: string | null }; deleted_in_filter: { document_id: number; text: string }[] };

/** A review write: the same function as its CLI command runs on the server, which answers with its refusal. */
async function send(path: string, body: Record<string, string | number>): Promise<void> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new ApiError(data, r.status);
}

function failureOf(e: unknown): Failure {
  return e instanceof ApiError ? e.failure : { cause: String(e), next_action: "Reload the page." };
}

function Problem({ failure }: { failure: Failure }) {
  return (
    <p className="problem" role="alert">
      {failure.cause} {failure.next_action}
    </p>
  );
}

function StatusLabel({ claim }: { claim: Claim }) {
  const l = label(claim.source_match, claim.source_match_reason);
  if (l.status === null) return <span className="not-checked">{l.text}</span>;
  return <span className={`status status-${l.status}`}>{l.text}</span>;
}

function figure(c: Claim): string {
  return c.unit_text ? `${c.value_text} ${c.unit_text}` : c.value_text;
}

type EsgCategory =
  | "GHG Emissions (Scope 1, 2 & 3)"
  | "Energy"
  | "Water"
  | "Waste & Materials"
  | "Targets & Intensity"
  | "Uncategorized / (no wording)";

const CATEGORY_ORDER: EsgCategory[] = [
  "GHG Emissions (Scope 1, 2 & 3)",
  "Energy",
  "Water",
  "Waste & Materials",
  "Targets & Intensity",
  "Uncategorized / (no wording)",
];

function categorizeClaim(c: Claim): EsgCategory {
  const mk = c.metric_key ?? "";
  const mt = (c.metric_text ?? "").toLowerCase();
  const ut = (c.unit_text ?? "").toLowerCase();

  if (!c.metric_text || c.metric_text.trim() === "" || c.metric_text === "(no wording)") {
    return "Uncategorized / (no wording)";
  }

  // GHG Emissions
  if (
    mk.startsWith("ghg_") ||
    /\b(ghg|scope\s*[123]|emissions?|carbon|co2e?)\b/i.test(mt) ||
    /co2/i.test(ut)
  ) {
    return "GHG Emissions (Scope 1, 2 & 3)";
  }

  // Energy
  if (
    mk.startsWith("energy_") ||
    /\b(gj|mwh|gwh|kwh|tj|btu)\b/i.test(ut) ||
    /\b(energy|electricity|fuel|power|renewable|non-renewable)\b/i.test(mt)
  ) {
    return "Energy";
  }

  // Water
  if (
    mk.startsWith("water_") ||
    /\b(kl|m3|m³|megalitres?|megaliters?|gallons?)\b/i.test(ut) ||
    /\b(water|effluent|discharge|withdrawal|consumption)\b/i.test(mt)
  ) {
    return "Water";
  }

  // Waste & Materials
  if (
    mk.startsWith("waste_") ||
    /\b(waste|plastic|aluminium|aluminum|copper|iron|steel|nickel|lithium|hazardous|scrap|materials?)\b/i.test(mt)
  ) {
    return "Waste & Materials";
  }

  // Targets & Intensity
  if (
    /\b(target|intensity|reduction|per\s+turnover|per\s+employee|per\s+tonne|net[-\s]zero)\b/i.test(mt) ||
    /%|percent/i.test(ut) ||
    /%/.test(c.value_text)
  ) {
    return "Targets & Intensity";
  }

  return "Uncategorized / (no wording)";
}

const EMPTY: CorrectionFields = { value: "", unit: "", metric: "", period_label: "", contributor: "", capacity: "", rationale: "" };
const FIELDS: [keyof CorrectionFields, string][] = [
  ["value", "Value"], ["unit", "Unit"], ["metric", "Metric wording"], ["period_label", "Period label"],
  ["contributor", "Contributor key"], ["capacity", "Capacity"], ["rationale", "Rationale"],
];

function CorrectionForm({ claimId, onDone }: { claimId: number; onDone: () => Promise<void> }) {
  const [f, setF] = useState(EMPTY);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      const r = await fetch(`/api/claims/${claimId}/corrections`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(correctionBody(f)),
      });
      const data = await r.json();
      if (!r.ok) throw new ApiError(data);
      setF(EMPTY);
      await onDone();
    } catch (err) {
      setFailure(failureOf(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="correct" onSubmit={submit}>
      <h3>Correct this figure</h3>
      {FIELDS.map(([k, text]) => (
        <label key={k}>
          {text}
          <input name={k} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
        </label>
      ))}
      <button type="submit" disabled={busy || !f.contributor.trim() || !f.capacity.trim() || !f.rationale.trim()}>
        Save correction
      </button>
      {failure && <Problem failure={failure} />}
    </form>
  );
}

// Story 5.4: the review forms. Each posts to the endpoint that calls its CLI command's function.
type Field = { name: string; label: string; kind?: "date" | "number" | "radio" | "select"; options?: [string, string][] };
type DocOption = { id: number; label: string };

function RecordForm({ title, path, fields, required, numbers, fixed, initial = {}, transform, submitLabel, onClose, onDone }: {
  title: string; path: string; fields: Field[]; required: string[]; numbers: string[];
  fixed: Record<string, string | number>; initial?: Record<string, string>; transform?: (f: Record<string, string>) => Record<string, string>;
  submitLabel: string; onClose: () => void; onDone: (refused: Failure | null) => Promise<void>;
}) {
  const [f, setF] = useState<Record<string, string>>(() => ({ ...Object.fromEntries(fields.map((x) => [x.name, ""])), ...initial }));
  const [failure, setFailure] = useState<Failure | null>(null);
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLFormElement>(null);
  useEffect(() => first.current?.querySelector<HTMLElement>("input, select")?.focus(), []);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      const data = transform ? transform(f) : f;
      await send(path, { ...recordBody(data, numbers), ...fixed });
      await onDone(null);
    } catch (err) {
      // 409: the claim or pair changed meanwhile (or the workspace is busy): the panel reloads and shows why.
      if (err instanceof ApiError && err.status === 409) await onDone(err.failure);
      else setFailure(failureOf(err));
    } finally {
      setBusy(false);
    }
  };
  const set = (k: string, v: string) => setF((old) => ({ ...old, [k]: v }));
  return (
    <form className="record" ref={first} onSubmit={submit} onKeyDown={(e) => e.key === "Escape" && onClose()}>
      <h4>{title}</h4>
      {fields.map((x) =>
        x.kind === "radio" ? (
          <fieldset key={x.name}>
            <legend>{x.label}</legend>
            {x.options!.map(([v, text]) => (
              <label key={v} className="choice">
                <input type="radio" name={x.name} value={v} checked={f[x.name] === v} onChange={() => set(x.name, v)} /> {text}
              </label>
            ))}
          </fieldset>
        ) : x.kind === "select" ? (
          <label key={x.name}>
            {x.label}
            <select name={x.name} value={f[x.name]} onChange={(e) => set(x.name, e.target.value)}>
              {x.options!.map(([v, text]) => (
                <option key={v} value={v}>{text}</option>
              ))}
            </select>
          </label>
        ) : (
          <label key={x.name}>
            {x.label}
            <input
              name={x.name}
              type={x.kind === "date" ? "date" : "text"}
              inputMode={x.kind === "number" ? "numeric" : undefined}
              value={f[x.name]}
              onChange={(e) => set(x.name, e.target.value)}
            />
          </label>
        ),
      )}
      <div className="buttons">
        <button type="submit" disabled={busy || required.some((k) => !f[k]?.trim())}>{submitLabel}</button>
        <button type="button" onClick={onClose}>Cancel</button>
      </div>
      {failure && <Problem failure={failure} />}
    </form>
  );
}

const WHO_FIELDS: Field[] = [{ name: "contributor", label: "Contributor key" }, { name: "capacity", label: "Capacity" }];
const OUTCOMES: [string, string][] = [["accepted", "accepted"], ["rejected", "rejected"], ["disputed", "disputed"]];

function ledgerFields(docs: DocOption[]): Field[] {
  return [
    ...WHO_FIELDS,
    { name: "outcome", label: "Outcome", kind: "radio", options: OUTCOMES },
    { name: "scope", label: "Scope (what you looked at)" },
    { name: "conclusion", label: "Conclusion (your words)" },
    { name: "date", label: "Date of your review", kind: "date" },
    { name: "evidence_document", label: "Evidence document", kind: "select",
      options: [["", "none (give a note)"], ...docs.map((d): [string, string] => [String(d.id), d.label])] },
    { name: "evidence_page", label: "Page of that document", kind: "number" },
    { name: "evidence_note", label: "Evidence note (outside the workspace, or a sheet and cell)" },
  ];
}

function EntryItem({ e, onJump }: { e: Entry; onJump: (t: { document: number; page: number }) => void }) {
  const target = evidenceTarget(e);
  const doc = e.evidence_document === null ? null
    : `document ${e.evidence_document}${e.evidence_page ? `, page ${e.evidence_page}` : ""} (${e.evidence_company}${target ? "" : `, ${e.evidence_state}`})`;
  return (
    <li className="entry">
      <span className={`dot dot-${e.outcome}`} aria-hidden="true" /> <span className="outcome">{e.outcome}</span>
      {!e.latest && <span className="meta"> · earlier entry</span>}
      <div>{whoText(e)} · {e.reviewed_on}</div>
      <div className="meta">Scope: {e.scope}</div>
      <div>“{e.conclusion}”</div>
      <div className="meta">
        Evidence:{" "}
        {doc && (target ? <button type="button" className="link" onClick={() => onJump(target)}>{doc}</button>
          : <button type="button" className="link" disabled>{doc}</button>)}
        {doc && e.evidence_note !== null && "; "}
        {e.evidence_note !== null && `note “${e.evidence_note}”`}
      </div>
      {e.evidence_deleted && <div className="meta">evidence deleted (document {e.evidence_deleted.document}, {e.evidence_deleted.at.slice(0, 10)})</div>}
    </li>
  );
}

function Column({ title, entries, onJump }: { title: string; entries: Entry[]; onJump: (t: { document: number; page: number }) => void }) {
  const { latest, earlier } = byPosition(entries);
  return (
    <div className="ledger">
      <h4>{title}</h4>
      {entries.length === 0 && <p className="hint">None on this version.</p>}
      <ul>{latest.map((e) => <EntryItem key={e.id} e={e} onJump={onJump} />)}</ul>
      {earlier.length > 0 && (
        <details open>
          <summary>show earlier entries ({earlier.length})</summary>
          <ul>{earlier.map((e) => <EntryItem key={e.id} e={e} onJump={onJump} />)}</ul>
        </details>
      )}
    </div>
  );
}

type FormKind = "company" | "auditor" | "highlight" | "raise" | "withdraw";

// The notice is held by App: a refusal is followed by a reload that remounts this panel on the new published
// version, and the refusal must still be on screen after it.
type Notice = { claim: number; failure: Failure } | null;

function Reviews({ claim, docs, notices, onNotice, onChanged, onJump }: {
  claim: Claim; docs: DocOption[]; notices: Notice; onNotice: (n: Notice) => void;
  onChanged: () => Promise<void>; onJump: (t: { document: number; page: number }) => void;
}) {
  const notice = notices?.claim === claim.id ? notices.failure : null;
  const setNotice = (f: Failure | null) => onNotice(f && { claim: claim.id, failure: f });
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [shown, setShown] = useState(0);
  const [form, setForm] = useState<FormKind | null>(null);
  const load = useCallback(async () => {
    const h = await get<{ versions: Version[] }>(`/api/claims/${claim.id}/history`);
    setVersions(h.versions);
    setShown(h.versions[h.versions.length - 1].id); // V2: the newest by default
  }, [claim.id]);
  useEffect(() => {
    load().catch((e) => onNotice({ claim: claim.id, failure: failureOf(e) }));
  }, [load, onNotice, claim.id]);
  if (!versions) return notice ? <Problem failure={notice} /> : null;
  const v = versions.find((x) => x.id === shown) ?? versions[versions.length - 1];
  const newest = versions[versions.length - 1];
  const writable = v.id === newest.id && claim.claim_state === "current";
  const band = bandText(v.disagreement);
  const done = async (refused: Failure | null) => {
    setForm(null);
    setNotice(refused);
    if (refused) await load(); // nothing was written, so the published version is the same
    await onChanged();
  };
  const common = { fixed: { version: v.id }, onClose: () => setForm(null), onDone: done };
  const flagRaiseFields: Field[] = [
    ...WHO_FIELDS,
    {
      name: "taxonomy_type",
      label: "EmeraldMind Greenwashing Taxonomy",
      kind: "radio",
      options: [
        ["Type 1: Unaccredited Label", "Type 1: Factually false or unaccredited label / certification"],
        ["Type 2: Mandated as Voluntary", "Type 2: Legal or statutory obligation framed as voluntary"],
        ["Type 3: Scope Mismatch", "Type 3: Boundary mismatch or scope overgeneralization"],
        ["Type 4: Direct Contradiction", "Type 4: Direct factual contradiction against reported table data"],
        ["General Concern", "General Auditor Concern / Other"],
      ],
    },
    { name: "rationale", label: "Auditor Rationale & Citation" },
  ];
  const flagWithdrawFields: Field[] = [...WHO_FIELDS, { name: "rationale", label: "Rationale" }];

  const formatFlagPayload = (data: Record<string, string>) => {
    const tax = data.taxonomy_type ? `[${data.taxonomy_type}] ` : "";
    const { taxonomy_type, ...rest } = data;
    return { ...rest, rationale: `${tax}${rest.rationale || ""}`.trim() };
  };

  const raised = v.reviewer_flags.some((f) => f.latest && f.decision === "raised");
  return (
    <section className="reviews" aria-label="Reviews">
      <h3>Reviews</h3>
      {notice && <Problem failure={notice} />}
      {versions.length > 1 && (
        <label className="version-pick">
          Version{" "}
          <select value={v.id} onChange={(e) => setShown(Number(e.target.value))}>
            {versions.map((x) => (
              <option key={x.id} value={x.id}>
                {x.id}: {x.value_text}{x.unit_text ? ` ${x.unit_text}` : ""}{x.id === newest.id ? " (newest)" : " (earlier, does not bind)"}
              </option>
            ))}
          </select>
        </label>
      )}
      {band && <p className="band">{band}</p>}
      <div className="ledgers">
        <Column title="Company confirmation" entries={v.company_confirmations} onJump={onJump} />
        <Column title="Auditor review" entries={v.auditor_reviews} onJump={onJump} />
      </div>
      {writable && (
        <div className="actions">
          <button type="button" className="link" onClick={() => setForm("company")}>Add a company confirmation</button>
          <button type="button" className="link" onClick={() => setForm("auditor")}>Add an auditor review</button>
          <button type="button" className="link" onClick={() => setForm("highlight")}>Highlight</button>
        </div>
      )}
      {(form === "company" || form === "auditor") && (
        <RecordForm
          key={form}
          title={form === "company" ? `Company confirmation on version ${v.id}` : `Auditor review on version ${v.id}`}
          path={`/api/claims/${claim.id}/${form === "company" ? "company-confirmations" : "auditor-reviews"}`}
          fields={ledgerFields(docs)}
          required={["contributor", "capacity", "outcome", "scope", "conclusion"]}
          numbers={["evidence_document", "evidence_page"]}
          initial={{ date: new Date().toLocaleDateString("en-CA") }}
          submitLabel="Record"
          {...common}
        />
      )}
      {form === "highlight" && (
        <RecordForm title={`Highlight version ${v.id}`} path={`/api/claims/${claim.id}/highlights`}
          fields={[...WHO_FIELDS, { name: "note", label: "Note" }]} required={["contributor", "capacity", "note"]}
          numbers={[]} submitLabel="Save highlight" {...common} />
      )}
      <h4>Highlights</h4>
      {v.highlights.length === 0 ? <p className="hint">None on this version.</p> : (
        <ul>
          {v.highlights.map((h) => (
            <li key={h.id}>
              {highlightText(h)} <span className="meta">version {h.claim_version}{h.latest ? "" : ", an earlier highlight"}</span>
            </li>
          ))}
        </ul>
      )}
      <h4>Reviewer flags</h4>
      {v.reviewer_flags.length === 0 ? <p className="hint">None on this version.</p> : (
        <ul>
          {v.reviewer_flags.map((f) => (
            <li key={f.id}>{flagText(f)}{f.latest ? "" : <span className="meta"> · an earlier position</span>}</li>
          ))}
        </ul>
      )}
      {writable && (
        <div className="actions">
          <button type="button" className="link" onClick={() => setForm("raise")}>Flag a potential greenwashing concern</button>
          {raised && <button type="button" className="link" onClick={() => setForm("withdraw")}>Withdraw your flag</button>}
        </div>
      )}
      {(form === "raise" || form === "withdraw") && (
        <RecordForm key={form} title={form === "raise" ? "Flag a potential greenwashing concern (EmeraldMind)" : "Withdraw your flag"}
          path={`/api/claims/${claim.id}/flags`} fields={form === "raise" ? flagRaiseFields : flagWithdrawFields}
          required={form === "raise" ? ["contributor", "capacity", "taxonomy_type", "rationale"] : ["contributor", "capacity", "rationale"]}
          transform={form === "raise" ? formatFlagPayload : undefined}
          numbers={[]} submitLabel={form === "raise" ? "Raise flag" : "Withdraw flag"} {...common}
          fixed={{ version: v.id, decision: form === "raise" ? "raised" : "withdrawn" }} />
      )}
      {hasRecords(versions) && <p className="declared">{SELF_DECLARED}</p>}
    </section>
  );
}

type Mark = { key: string; boxes: Box[]; selected: boolean; onClick?: () => void };

function PageImage({ docId, name, page, size, sharp, marks }: {
  docId: number; name: string; page: number; size: PageSize; sharp: boolean; marks: Mark[];
}) {
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const src = `/api/documents/${docId}/pages/${page}.png?scale=${sharp ? "3.0" : "1.5"}`;
  return (
    <div className="page" style={{ aspectRatio: `${size.width} / ${size.height}` }}>
      {/* keyed by src: an image of another page or document is never left under these boxes */}
      <img key={src} src={src} alt={`Page ${page} of ${name}`} onLoad={() => setLoadedSrc(src)} />
      {overlayShown(loadedSrc, src) && (
        <svg viewBox={`${size.left} ${size.top} ${size.width} ${size.height}`} aria-hidden="true">
          {marks.flatMap((m) =>
            m.boxes.map(([x0, top, x1, bottom], k) => (
              <rect key={`${m.key}-${k}`} className={m.selected ? "box box-selected" : "box"} x={x0} y={top}
                width={x1 - x0} height={bottom - top} onClick={m.onClick} />
            )),
          )}
        </svg>
      )}
    </div>
  );
}

type Side = { claim_id: number; document_id: number; page_number: number | null; value_text: string; unit_text: string | null };
type Candidate = {
  metric_key: string | null; label: string; reporting_boundary: string; period_start: string; period_end: string;
  a: Side; b: Side; adjudication_state: string; adjudications: unknown[];
};

function sideText(s: Side, docName: (id: number) => string): string {
  return `${s.value_text}${s.unit_text ? ` ${s.unit_text}` : ""} (${docName(s.document_id)}, ${s.page_number === null ? "no page" : `page ${s.page_number}`}, claim ${s.claim_id})`;
}

function PairSide({ side, docName }: { side: Side; docName: (id: number) => string }) {
  const [shown, setShown] = useState<{ size: PageSize; boxes: Box[] } | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  useEffect(() => {
    (async () => {
      const [info, list] = await Promise.all([
        get<{ pages: PageSize[] }>(`/api/documents/${side.document_id}`),
        get<{ claims: Claim[] }>(`/api/documents/${side.document_id}/claims`),
      ]);
      const c = list.claims.find((x) => x.id === side.claim_id);
      const size = side.page_number === null ? undefined : info.pages[side.page_number - 1];
      if (!size) throw new ApiError({ cause: `Claim ${side.claim_id} is not on a page of this document.`, next_action: "" });
      setShown({ size, boxes: c?.boxes ?? [] });
    })().catch((e) => setFailure(failureOf(e)));
  }, [side.document_id, side.claim_id, side.page_number]);
  return (
    <div className="side">
      <p className="figure">{sideText(side, docName)}</p>
      {failure && <p className="hint">{failure.cause}</p>}
      {shown && (
        <PageImage docId={side.document_id} name={docName(side.document_id)} page={side.page_number!} size={shown.size}
          sharp={false} marks={[{ key: String(side.claim_id), boxes: shown.boxes, selected: true }]} />
      )}
    </div>
  );
}

function Candidates({ company, docs, docName }: { company: Company; docs: DocOption[]; docName: (id: number) => string }) {
  const [list, setList] = useState<Candidate[] | null>(null);
  const [open, setOpen] = useState<Candidate | null>(null);
  const [notice, setNotice] = useState<Failure | null>(null);
  const load = useCallback(async () => {
    setList((await get<{ candidates: Candidate[] }>(`/api/companies/${company.id}/candidates`)).candidates);
  }, [company.id]);
  useEffect(() => {
    load().catch((e) => setNotice(failureOf(e)));
  }, [load]);
  const done = async (refused: Failure | null) => {
    setNotice(refused);
    setOpen(null);
    await load();
  };
  if (open) {
    const [a, b] = [open.a.claim_id, open.b.claim_id];
    return (
      <div className="pair">
        <button type="button" className="link" onClick={() => setOpen(null)}>Back to the candidates</button>
        <h2>{open.metric_key ?? `unmapped: ${open.label}`}, {open.period_start}..{open.period_end}: {open.adjudication_state}</h2>
        <div className="sides">
          <PairSide side={open.a} docName={docName} />
          <PairSide side={open.b} docName={docName} />
        </div>
        <RecordForm
          title="Adjudicate this candidate"
          path="/api/adjudications"
          fields={[
            { name: "state", label: "State", kind: "select", options: [["", "choose a state"], ...ADJUDICATION_STATES] },
            { name: "rationale", label: "Rationale" }, { name: "procedure", label: "Procedure (how you checked)" },
            { name: "counter_document", label: "Counter-evidence document", kind: "select",
              options: [["", "none"], ...docs.map((d): [string, string] => [String(d.id), d.label])] },
            { name: "counter_page", label: "Page of that document", kind: "number" },
            { name: "counter_note", label: "Counter-evidence note" }, { name: "follow_up", label: "Follow-up" },
            { name: "closure_reason", label: "Closure reason" }, ...WHO_FIELDS,
          ]}
          required={["state", "rationale", "procedure", "contributor", "capacity"]}
          numbers={["counter_document", "counter_page"]}
          fixed={{ first: a, second: b }}
          submitLabel="Record adjudication"
          onClose={() => setOpen(null)}
          onDone={done}
        />
        <p className="hint">
          A restatement is recorded with its page and quote: <code>{restateCommand(a, b)}</code> (the original figure's
          claim first)
        </p>
        <p className="declared">{SELF_DECLARED}</p>
      </div>
    );
  }
  return (
    <div className="candidates">
      <h2>Candidates: {company.name}</h2>
      {notice && <Problem failure={notice} />}
      {list && list.length === 0 && <p className="hint">No candidates. A candidate is an unresolved conflict found by gct match.</p>}
      <ul>
        {list?.map((c) => (
          <li key={`${c.a.claim_id}-${c.b.claim_id}`}>
            <button type="button" className="candidate" onClick={() => setOpen(c)}>
              <span className="wording">{c.metric_key ?? `unmapped: ${c.label}`} · {c.reporting_boundary} · {c.period_start}..{c.period_end}</span>
              <span>{sideText(c.a, docName)}</span>
              <span>{sideText(c.b, docName)}</span>
              <span className="meta">{c.adjudication_state}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

const NO_CHIPS: Record<Tab, Chip | null> = { tables: null, graphs: null };

export function App() {
  const [health, setHealth] = useState<{ gct_version: string; data_version: number | null } | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [opened, setOpened] = useState<Opened | null>(null);
  const [page, setPage] = useState(1);
  const [pageBox, setPageBox] = useState("1");
  const [claims, setClaims] = useState<Claim[]>([]);
  const [selected, setSelected] = useState(-1);
  const [sharp, setSharp] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [candidatesOf, setCandidatesOf] = useState<Company | null>(null); // the Candidates view of one company
  const [reviewNotice, setReviewNotice] = useState<Notice>(null); // outlives the Reviews remount after a reload
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  const docRequests = useRef(newestOnly()).current;
  // Tables and Graphs (story 6.1, H): one filter on one pinned data version; a newer version is offered, never mixed in.
  const [section, setSection] = useState<"evidence" | "records">("evidence");
  const [tab, setTab] = useState<"tables" | "graphs" | "restate">("tables");
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [filter, setFilter] = useState<Filter>({});
  const [pinned, setPinned] = useState<number | null>(null);
  const [newer, setNewer] = useState<number | null>(null);
  const [count, setCount] = useState<Count | null>(null);
  const [countFailure, setCountFailure] = useState<Failure | null>(null);
  const [series, setSeries] = useState<SeriesValue[]>([]);
  const [cellAt, setCellAt] = useState<EvidenceTarget | null>(null);
  const pendingClaim = useRef<number | null>(null); // the claim openEvidence selects once its document's claims load
  const countRequests = useRef(newestOnly()).current;
  // Story 6.4 part B: what each tab has selected (6.2 T-G, 6.3 S5b), the chip each tab received by a transfer (never
  // stored; dropped with a filter-bar change or a new version), and the open panel under the filter bar.
  const [sent, setSent] = useState<Record<Tab, Sent>>({ tables: null, graphs: null });
  const [chips, setChips] = useState<Record<Tab, Chip | null>>(NO_CHIPS);
  const [panel, setPanel] = useState<"views" | "questions" | null>(null);
  const [claimSearch, setClaimSearch] = useState("");
  const [currentPageOnly, setCurrentPageOnly] = useState(false);

  const open = async (d: Doc, at = 1) => {
    const id = docRequests.start();
    setCandidatesOf(null);
    setFailure(null);
    setOpened(null);
    setSelected(-1);
    setClaims([]);
    try {
      const [info, list] = await Promise.all([
        get<{ pages: PageSize[] }>(`/api/documents/${d.id}`),
        get<{ claims: Claim[] }>(`/api/documents/${d.id}/claims`),
      ]);
      if (!docRequests.isCurrent(id)) return; // another document was chosen meanwhile
      setOpened({ id: d.id, name: d.logical_name, pages: info.pages });
      setPage(stepPage(at, 0, info.pages.length));
      setClaims(list.claims);
    } catch (e) {
      if (docRequests.isCurrent(id)) setFailure(failureOf(e));
    }
  };

  const changeFilter = useCallback((f: Filter) => {
    setFilter(f);
    setChips(NO_CHIPS);
  }, []);
  const sentByTables = useCallback((s: Sent) => setSent((o) => ({ ...o, tables: s })), []);
  const sentByGraphs = useCallback((s: Sent) => setSent((o) => ({ ...o, graphs: s })), []);

  const loadCompanies = async () => {
    const { companies } = await get<{ companies: { id: number; name: string }[] }>("/api/companies");
    const loaded = await Promise.all(
      companies.map(async (c) => ({
        ...c,
        documents: (await get<{ documents: Doc[] }>(`/api/companies/${c.id}/documents`)).documents,
      })),
    );
    setCompanies(loaded);
    return loaded;
  };

  useEffect(() => {
    (async () => {
      try {
        const h = await get<{ gct_version: string; data_version: number | null }>("/api/health");
        setHealth(h);
        setPinned(h.data_version);
        await loadCompanies();
      } catch (e) {
        setFailure(failureOf(e));
      }
    })();
  }, []);

  // Another writer published meanwhile: offer the new version. The pin is read when the answer arrives, so an answer
  // that arrives after Reload does not offer the version just taken.
  const pinnedNow = useRef(pinned);
  pinnedNow.current = pinned;
  const checkVersion = async () => {
    const h = await get<{ gct_version: string; data_version: number | null }>("/api/health");
    setHealth(h);
    setNewer(newerVersion(pinnedNow.current, h.data_version));
    return h.data_version;
  };

  useEffect(() => {
    if (pinned === null) return;
    const id = countRequests.start();
    setCount(null);
    setCountFailure(null);
    // Each change asks again; an older answer that arrives late is dropped (NFR1: no blocking wait).
    records<Count>(recordsBody(filter, pinned, "table", 0, 1)).then(
      (c) => countRequests.isCurrent(id) && setCount(c),
      (e) => {
        if (!countRequests.isCurrent(id)) return;
        if (e instanceof ApiError && isStale(e.status, e.failure.cause)) checkVersion().catch(() => setCountFailure(failureOf(e)));
        else setCountFailure(failureOf(e));
      },
    );
  }, [filter, pinned]);

  useEffect(() => {
    if (pinned === null) return;
    records<{ series: SeriesValue[] }>({ filter: {}, data_version: pinned, shape: "values" }).then(
      (v) => setSeries(v.series),
      () => setSeries([]), // the count line shows why the version cannot be read
    );
  }, [pinned]);

  const takeVersion = async (version: number) => {
    setNewer(null);
    setPinned(version);
    setChips(NO_CHIPS);
    await loadCompanies().catch((e) => setCountFailure(failureOf(e)));
  };

  // B1: a transfer switches tab; the receiving tab shows the selection with its chip, the filter and the pin stay.
  // Focus goes to that tab: the pressed bar button is drawn again for the receiving tab, often disabled.
  const transfer = (to: Tab, chip: Chip) => {
    setChips((c) => ({ ...c, [to]: chip }));
    setTab(to);
    document.getElementById(`tab-${to}`)?.focus();
  };

  const removeChip = () => {
    setChips((c) => ({ ...c, [tab]: null }));
    document.getElementById(`tab-${tab}`)?.focus(); // the chip and its button are gone
  };

  // B2, B3: a saved view or a question replaces the filter and opens its tab; a saved view opens on the current
  // version, taken here as Reload takes it.
  const choose = ({ filter: f, section: to, chip }: Chosen) => {
    setPanel(null);
    setFilter(f);
    setChips({ ...NO_CHIPS, ...(chip ? { [to]: chip } : {}) });
    setTab(to);
  };

  const openView = async (v: SavedView) => {
    const now = await checkVersion().catch(() => pinnedNow.current);
    if (now !== null && now !== pinnedNow.current) await takeVersion(now);
    choose({ filter: v.filter, section: v.section });
  };

  const showRecords = () => {
    setSection("records");
    checkVersion().catch(() => undefined); // the count request reports a failure itself
  };

  useEffect(() => setPageBox(String(page)), [page]);

  const docs = companies.flatMap((c) => c.documents.map((d) => ({ ...d, company: c.name })));
  const docOptions = docs.map((d) => ({ id: d.id, label: `${d.company}: ${d.logical_name}${d.version > 1 ? ` v${d.version}` : ""}` }));
  const docName = (id: number) => docs.find((d) => d.id === id)?.logical_name ?? `document ${id}`;

  // An evidence link: the cited page, in this document or after opening the cited one.
  const jump = async (t: { document: number; page: number }) => {
    if (opened?.id === t.document) return setPage(stepPage(t.page, 0, opened.pages.length));
    const d = docs.find((x) => x.id === t.document);
    if (d) await open(d, t.page);
    else setFailure({ cause: `Document ${t.document} is not in the published data.`, next_action: "Build a fresh version with: gct publish build" });
  };

  // After a correction: the new published version's claims, the same claim still selected.
  const reload = async () => {
    const [h, list] = await Promise.all([
      get<{ gct_version: string; data_version: number | null }>("/api/health"),
      get<{ claims: Claim[] }>(`/api/documents/${opened!.id}/claims`),
    ]);
    setHealth(h);
    setNewer(newerVersion(pinnedNow.current, h.data_version)); // the write built a new version; Tables and Graphs offers it
    setSelected(list.claims.findIndex((c) => c.id === claims[selected].id));
    setClaims(list.claims);
  };

  const pageCount = opened ? opened.pages.length : 0;

  const select = useCallback(
    (index: number) => {
      setSelected(index);
      setReviewNotice(null); // a refusal belongs to the claim it was shown on
      const c = claims[index];
      if (!c) return;
      if (decide(c, pageCount) !== "do not navigate") setPage(c.page!);
      items.current[index]?.scrollIntoView({ block: "nearest" });
    },
    [claims, pageCount],
  );

  // F11 f: a page of a PDF opens in the Evidence section with its claim selected; a cell opens the cell view here.
  const openEvidence = async (t: EvidenceTarget) => {
    if (isCell(t)) return setCellAt(t);
    setSection("evidence");
    const at = claims.findIndex((c) => c.id === t.claim_id);
    if (opened?.id === t.document && !candidatesOf && at >= 0) return select(at);
    pendingClaim.current = t.claim_id ?? null;
    await jump({ document: t.document, page: t.page ?? 1 });
  };

  useEffect(() => {
    if (pendingClaim.current === null || claims.length === 0) return;
    const at = claims.findIndex((c) => c.id === pendingClaim.current);
    pendingClaim.current = null; // a claim not in the current version leaves the page open, nothing selected
    if (at >= 0) select(at);
  }, [claims, select]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (section === "records") return; // the arrows belong to the Evidence section only
      if (!opened || candidatesOf || ["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName) || e.altKey || e.ctrlKey
          || e.metaKey) return;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        setPage((p) => stepPage(p, e.key === "ArrowLeft" ? -1 : 1, pageCount));
      } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        select(stepClaim(selected, e.key === "ArrowUp" ? -1 : 1, claims.length));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [section, opened, candidatesOf, pageCount, selected, claims.length, select]);

  const goTo = () => {
    const n = Number(pageBox);
    if (Number.isInteger(n) && n >= 1 && n <= pageCount) setPage(n);
    else setPageBox(String(page));
  };

  const current = claims[selected];
  const decision = current ? decide(current, pageCount) : null;
  const size = opened?.pages[page - 1];
  const onPage = claims
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => c.page === page && decide(c, pageCount) === "jump and highlight")
    .sort((a, b) => Number(a.i === selected) - Number(b.i === selected)); // the selected box is drawn last, on top

  const filteredClaims = claims
    .map((c, originalIndex) => ({ c, originalIndex }))
    .filter(({ c }) => {
      if (currentPageOnly && c.page !== page) return false;
      if (!claimSearch.trim()) return true;
      const q = claimSearch.toLowerCase().trim();
      const wording = (c.metric_text ?? "").toLowerCase();
      const val = (c.value_text ?? "").toLowerCase();
      const unit = (c.unit_text ?? "").toLowerCase();
      const period = (c.period_label ?? "").toLowerCase();
      return wording.includes(q) || val.includes(q) || unit.includes(q) || period.includes(q);
    });

  const categorizedClaims = CATEGORY_ORDER.map((category) => {
    const items = filteredClaims.filter(({ c }) => categorizeClaim(c) === category);
    return { category, items };
  }).filter(({ items }) => items.length > 0);

  return (
    <div className="shell">
      <header>
        <h1>GoCarbonTracker</h1>
        {health && (
          <span className="meta">
            gct {health.gct_version},{" "}
            {health.data_version === null ? "no published version yet" : `published data version ${health.data_version}`}
          </span>
        )}
        <div className="sections" role="group" aria-label="Section">
          <button aria-pressed={section === "evidence"} onClick={() => setSection("evidence")}>Evidence</button>
          <button aria-pressed={section === "records"} onClick={showRecords}>Tables and Graphs</button>
        </div>
      </header>

      <section className="records" aria-label="Tables and Graphs" hidden={section !== "records"}>
        {newer !== null && (
          <p className="notice" role="status">
            {availableText(newer)} <button onClick={() => takeVersion(newer)}>Reload</button>
          </p>
        )}
        {pinned === null ? (
          <p className="hint">No published data yet. Run: gct publish build</p>
        ) : (
          <>
            <FilterBar filter={filter} onChange={changeFilter} companies={companies} series={series} />
            <div className="panel-buttons">
              <button type="button" aria-expanded={panel === "views"} aria-controls="panel-views"
                onClick={() => setPanel(panel === "views" ? null : "views")}>Saved views</button>
              <button type="button" aria-expanded={panel === "questions"} aria-controls="panel-questions"
                onClick={() => setPanel(panel === "questions" ? null : "questions")}>Questions</button>
            </div>
            {panel === "views" && <SavedViews filter={filter} tab={tab === "restate" ? "tables" : tab} chipShown={tab !== "restate" && chips[tab] !== null}
              onOpen={(v) => { openView(v).catch((e) => setCountFailure(failureOf(e))); }} onClose={() => setPanel(null)} />}
            {panel === "questions" && <Questions pinned={pinned} onChoose={choose} onClose={() => setPanel(null)}
              onStale={() => { checkVersion().catch(() => undefined); }} />}
            <div className="count" aria-live="polite">
              {countFailure && <Problem failure={countFailure} />}
              {!count && !countFailure && <p className="hint">Counting the claims of data version {pinned}.</p>}
              {count && (
                <>
                  <p className="count-line">{countText(count.matched, count.data_version)}</p>
                  {count.empty && <p>{count.empty}</p>}
                  {periodUnknownText(count.excluded.period_unknown) && <p className="meta">{periodUnknownText(count.excluded.period_unknown)}</p>}
                  {count.hidden_by_archive.text && <p className="meta">{count.hidden_by_archive.text}</p>}
                  {count.deleted_in_filter.map((d) => <p key={d.document_id} className="meta">{d.text}</p>)}
                </>
              )}
              {tab !== "restate" && chips[tab] && <ChipLine chip={chips[tab]!} onRemove={removeChip} />}
            </div>
            {cellAt && <CellView key={JSON.stringify(cellAt)} target={cellAt} pinned={pinned} onClose={() => setCellAt(null)} />}
            <div className="tabs" role="tablist" aria-label="Tables, Graphs or Restatements">
              <button role="tab" id="tab-tables" aria-controls="body-tables" aria-selected={tab === "tables"}
                onClick={() => setTab("tables")}>Tables</button>
              <button role="tab" id="tab-graphs" aria-controls="body-graphs" aria-selected={tab === "graphs"}
                onClick={() => setTab("graphs")}>Graphs</button>
              <button role="tab" id="tab-restate" aria-controls="body-restate" aria-selected={tab === "restate"}
                onClick={() => setTab("restate")}>Restatements</button>
              <button type="button" className="copilot-toggle-btn" onClick={() => setCopilotOpen(!copilotOpen)}>
                🛡️ Copilot Proposals
              </button>
            </div>
            {tab !== "restate" && <Transfer tab={tab} sent={sent[tab]} pinned={pinned} newer={newer} current={checkVersion} onTransfer={transfer} />}
            {/* Story 6.2 renders its table here, 6.3 its graphs, and 6.5 restatements matrix */}
            <div role="tabpanel" id="body-tables" aria-labelledby="tab-tables" hidden={tab !== "tables"}>
              <Tables filter={filter} dataVersion={pinned} openEvidence={openEvidence} onStale={() => { checkVersion().catch(() => undefined); }}
                selection={chips.tables?.selection ?? null} onSelectionChange={sentByTables} />
            </div>
            <div role="tabpanel" id="body-graphs" aria-labelledby="tab-graphs" hidden={tab !== "graphs"}>
              <Suspense fallback={null}><Graphs filter={filter} dataVersion={pinned} openEvidence={openEvidence} onStale={() => { checkVersion().catch(() => undefined); }}
                selection={chips.graphs?.selection ?? null} onSelectionChange={sentByGraphs} /></Suspense>
            </div>
            <div role="tabpanel" id="body-restate" aria-labelledby="tab-restate" hidden={tab !== "restate"}>
              {tab === "restate" && <RestatementsTab openEvidence={openEvidence} />}
            </div>
            <CopilotDrawer
              open={copilotOpen}
              onClose={() => setCopilotOpen(false)}
              onSelectCandidate={(c) => {
                openEvidence({ document: c.document_id, page: c.page_number, claim_id: c.claim_id });
              }}
              onFlagCandidate={(c) => {
                openEvidence({ document: c.document_id, page: c.page_number, claim_id: c.claim_id });
                setCopilotOpen(false);
              }}
            />
          </>
        )}
      </section>

      <nav aria-label="Companies and documents" hidden={section !== "evidence"}>
        {health?.data_version === null && <p className="hint">No published data yet. Run: gct publish build</p>}
        {companies.map((c) => (
          <section key={c.id}>
            <h2>{c.name}</h2>
            {c.documents.length === 0 && <p className="hint">No documents.</p>}
            <ul>
              {c.documents.map((d) => (
                <li key={d.id}>
                  <button className="doc" aria-current={!candidatesOf && opened?.id === d.id} onClick={() => open(d)}>
                    {d.logical_name}
                    {d.version > 1 && <span className="meta"> v{d.version}</span>}
                  </button>
                </li>
              ))}
              <li>
                <button className="doc" aria-current={candidatesOf?.id === c.id} onClick={() => setCandidatesOf(c)}>
                  Candidates
                </button>
              </li>
            </ul>
          </section>
        ))}
      </nav>

      <main hidden={section !== "evidence"}>
        {failure && <Problem failure={failure} />}
        {candidatesOf && <Candidates key={candidatesOf.id} company={candidatesOf} docs={docOptions} docName={docName} />}
        {!opened && !failure && !candidatesOf && <p className="hint">Choose a document on the left.</p>}
        {opened && !candidatesOf && (
          <>
            <div className="toolbar">
              <button onClick={() => setPage(stepPage(page, -1, pageCount))} disabled={page <= 1}>
                Previous
              </button>
              <label>
                Page{" "}
                <input
                  className="page-box"
                  inputMode="numeric"
                  value={pageBox}
                  onChange={(e) => setPageBox(e.target.value)}
                  onBlur={goTo}
                  onKeyDown={(e) => e.key === "Enter" && goTo()}
                />
              </label>
              <span>of {pageCount}</span>
              <button onClick={() => setPage(stepPage(page, 1, pageCount))} disabled={page >= pageCount}>
                Next
              </button>
              <label className="sharp">
                <input type="checkbox" checked={sharp} onChange={(e) => setSharp(e.target.checked)} /> Sharper image
              </label>
            </div>

            {current && (
              <div className="selected" aria-live="polite">
                <p className="claim-text">{current.metric_text ?? "(no wording)"}</p>
                <dl>
                  <dt>Value</dt>
                  <dd>{figure(current)}</dd>
                  <dt>Period</dt>
                  <dd>{periodText(current)}</dd>
                  <dt>Boundary</dt>
                  <dd>{boundaryText(current)}</dd>
                  {current.boundary_label !== null && (
                    <>
                      <dt>Boundary label</dt>
                      <dd>{current.boundary_label}</dd>
                    </>
                  )}
                  <dt>State</dt>
                  <dd>{current.claim_state}</dd>
                  {current.correction && (
                    <>
                      <dt>Corrected</dt>
                      <dd>{correctionText(current.correction)}</dd>
                    </>
                  )}
                  {current.needs_re_review.map((e) => (
                    <Fragment key={`${e.kind}-${e.id}`}>
                      <dt>Needs re-review</dt>
                      <dd>{reReviewText(e)}</dd>
                    </Fragment>
                  ))}
                  <dt>Source</dt>
                  <dd>
                    <StatusLabel claim={current} />
                  </dd>
                </dl>
                {current.claim_state === "current" && <CorrectionForm key={current.id} claimId={current.id} onDone={reload} />}
                {decision === "do not navigate" && (
                  <p className="hint">
                    {current.page === null
                      ? "This claim is not on a page, so the page was not changed."
                      : `Page ${current.page} is not in this document, so the page was not changed.`}
                  </p>
                )}
                {/* keyed by the published version: after any write the panel reads the history again */}
                <Reviews key={`${current.id}-${health?.data_version}`} claim={current} docs={docOptions}
                  notices={reviewNotice} onNotice={setReviewNotice} onChanged={reload}
                  onJump={jump} />
              </div>
            )}

            {size && (
              <PageImage docId={opened.id} name={opened.name} page={page} size={size} sharp={sharp}
                marks={onPage.map(({ c, i }) => ({ key: `${c.id}-${i}`, boxes: c.boxes!, selected: i === selected,
                                                   onClick: () => select(i) }))} />
            )}
          </>
        )}
      </main>

      <aside aria-label="Claims" hidden={section !== "evidence"}>
        <h2>Claims</h2>
        {candidatesOf && <p className="hint">Choose a document on the left to see its claims.</p>}
        {opened && !candidatesOf && claims.length === 0 && <p className="hint">No claims for this document. Run: gct extract</p>}
        {!candidatesOf && opened && (
          <div className="claims-controls">
            <input
              type="search"
              className="claims-search"
              placeholder="Search claims..."
              value={claimSearch}
              onChange={(e) => setClaimSearch(e.target.value)}
              aria-label="Search claims"
            />
            <label className="claims-page-toggle">
              <input
                type="checkbox"
                checked={currentPageOnly}
                onChange={(e) => setCurrentPageOnly(e.target.checked)}
              />
              {" "}Current page only
            </label>
          </div>
        )}
        <div className="claims-groups" hidden={!!candidatesOf}>
          {categorizedClaims.map(({ category, items: catItems }) => (
            <details
              key={category}
              className="claim-category"
              open={category !== "Uncategorized / (no wording)"}
            >
              <summary>
                {category} <span className="meta">({catItems.length})</span>
              </summary>
              <ul>
                {catItems.map(({ c, originalIndex }) => (
                  <li key={`${c.id}-${originalIndex}`}>
                    <button
                      ref={(el) => {
                        items.current[originalIndex] = el;
                      }}
                      className="claim"
                      aria-pressed={originalIndex === selected}
                      onClick={() => select(originalIndex)}
                    >
                      <span className="figure">{figure(c)}</span>
                      <span className="wording">{c.metric_text ?? "(no wording)"}</span>
                      <span className="meta">
                        {[
                          c.period_label,
                          c.page === null ? "no page" : `page ${c.page}`,
                          c.claim_state !== "current" ? c.claim_state : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                      <StatusLabel claim={c} />
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          ))}
          {!candidatesOf && opened && claims.length > 0 && categorizedClaims.length === 0 && (
            <p className="hint">No claims match the filter.</p>
          )}
        </div>
      </aside>
    </div>
  );
}
