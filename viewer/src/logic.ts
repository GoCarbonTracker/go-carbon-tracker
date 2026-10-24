// Pure viewer logic, tested with `node --test` (Node strips the types): no imports, no enums.

export type Box = [number, number, number, number]; // x0, top, x1, bottom in PDF points, top-left origin

export type Claim = {
  id: number;
  locator: string;
  metric_text: string | null;
  metric_key?: string | null;
  value?: number | null;
  value_text: string;
  unit_text: string | null;
  period_label: string | null; // as printed
  // Published values: only accepted or resolved dates and boundaries; a proposal never arrives here.
  period_kind: string | null;
  period_start: string | null;
  period_end: string | null;
  period_state: string; // resolved, accepted, proposed, unresolved or extracted
  reporting_boundary: string;
  boundary_detail: string | null;
  boundary_state: string;
  page: number | null; // the evidence page; null when the evidence is not on a page
  boxes: Box[] | null;
  source_match: "matched" | "cited" | "unresolved" | null; // null: no source-match row yet
  source_match_reason: string | null;
  claim_state: string; // current, not found in the newest reading, or page read again, not yet extracted
  version_method: string;
  boundary_label: string | null; // the boundary header printed above the column, as printed
  correction: Correction | null; // set when the current version is a contributor's correction
  needs_re_review: { kind: string; id: number; version: number; with?: { claim: number; version: number } }[];
};

export type Correction = {
  contributor: string;
  capacity: string;
  rationale: string;
  replaced: { value_text: string };
};

/** A contributor's correction: who, in what capacity, why, and the value it replaced. */
export function correctionText(c: Correction): string {
  return `${c.contributor} (${c.capacity}): ${c.rationale}; replaced ${c.replaced.value_text}`;
}

export type CorrectionFields = {
  value: string; unit: string; metric: string; period_label: string;
  contributor: string; capacity: string; rationale: string;
};

/** The POST body: empty optional fields are left out, and everything is trimmed. */
export function correctionBody(f: CorrectionFields): Record<string, string> {
  const body: Record<string, string> = {};
  for (const [k, v] of Object.entries(f)) if (v.trim() !== "") body[k] = v.trim();
  return body;
}

/** One needs-re-review entry, as the CLI prints it (an adjudication names the other side). */
export function reReviewText(e: Claim["needs_re_review"][number]): string {
  const other = e.with ? ` with claim ${e.with.claim} version ${e.with.version}` : "";
  return `${e.kind} #${e.id} on version ${e.version}${other}`;
}

// Story 5.4: the records of people outside GCT on one claim version, as the history endpoint returns them.

export const SELF_DECLARED =
  "Identities and capacities are self-declared. GCT does not check them and does not adopt any conclusion as its own.";

type Who = { contributor: string; organisation: string | null; capacity: string; latest: boolean };
export type Deleted = { document: number; at: string } | null;
export type Entry = Who & {
  id: number; outcome: "accepted" | "rejected" | "disputed"; reviewed_on: string; scope: string; conclusion: string;
  evidence_document: number | null; evidence_company: string | null; evidence_page: number | null;
  evidence_note: string | null; evidence_state: string | null; evidence_deleted: Deleted;
};
export type Flag = Who & { id: number; decision: "raised" | "withdrawn"; rationale: string };
export type Highlight = Who & { id: number; claim_version: number; note: string; evidence_deleted: Deleted };
export type Disagreement = { company: string[]; auditor: string[] } | null;
export type Version = {
  id: number; value_text: string; unit_text: string | null;
  company_confirmations: Entry[]; auditor_reviews: Entry[]; disagreement: Disagreement;
  reviewer_flags: Flag[]; adjudications: unknown[]; highlights: Highlight[];
};

/** The band across both columns, or null when the two ledgers do not disagree on this version. */
export function bandText(d: Disagreement): string | null {
  if (!d) return null;
  return `Company confirmation and auditor review disagree on this version: company ${d.company.join(", ")}; auditor ${d.auditor.join(", ")}.`;
}

/** A column's entries: each contributor's latest position first, then their earlier entries (none is hidden). */
export function byPosition<T extends { latest: boolean }>(entries: T[]): { latest: T[]; earlier: T[] } {
  return { latest: entries.filter((e) => e.latest), earlier: entries.filter((e) => !e.latest) };
}

/** Who, as they declared it: name (organisation), capacity. */
export function whoText(e: Who): string {
  return `${e.contributor}${e.organisation ? ` (${e.organisation})` : ""}, ${e.capacity}`;
}

/** The self-declared line goes on every claim with an entry of any kind on any version. */
export function hasRecords(versions: Version[]): boolean {
  return versions.some((v) => v.company_confirmations.length + v.auditor_reviews.length + v.reviewer_flags.length
    + v.adjudications.length + v.highlights.length > 0);
}

/** The cited page an entry's evidence link jumps to: only a workspace document that is still active. */
export function evidenceTarget(e: Entry): { document: number; page: number } | null {
  if (e.evidence_document === null || e.evidence_deleted) return null;
  if (e.evidence_state !== "registered" && e.evidence_state !== "restored") return null;
  return { document: e.evidence_document, page: e.evidence_page ?? 1 };
}

export function highlightText(h: Highlight): string {
  return `Highlighted by ${h.contributor}${h.organisation ? ` (${h.organisation})` : ""} (self-declared): ${h.note}`;
}

export function flagText(f: Flag): string {
  const who = `${f.contributor}${f.organisation ? ` (${f.organisation})` : ""}`;
  return `Potential greenwashing concern ${f.decision} by ${who} (self-declared): ${f.rationale}`;
}

/** The JSON body of a review form: empty fields left out, text kept exactly as typed, the named fields as numbers. */
export function recordBody(f: Record<string, string>, numbers: string[]): Record<string, string | number> {
  const body: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(f)) {
    if (v.trim() === "") continue;
    body[k] = numbers.includes(k) ? Number(v) : v;
  }
  return body;
}

/** The adjudication states a reviewer can record, as the CLI takes them: no restatement (V3). */
export const ADJUDICATION_STATES: [string, string][] = [
  ["explained-difference", "explained difference"], ["extraction-error", "extraction error"],
  ["reviewer-confirmed-issue", "reviewer-confirmed issue"], ["evidence-not-found", "evidence not found"],
];

/** The command that records a restatement instead, to copy (V3). */
export function restateCommand(original: number, restated: number): string {
  return `gct restate record --original ${original} --restated ${restated} --page N --quote "TEXT"`;
}

export type Label = { status: "matched" | "cited" | "unresolved" | null; text: string };

export const NOT_CHECKED = "not checked: run gct link";

/** The source-match label: three statuses with their reason as stored, and a plain line when not checked. */
export function label(status: Claim["source_match"], reason: string | null): Label {
  if (status === null) return { status: null, text: NOT_CHECKED };
  return { status, text: reason ? `${status}: ${reason}` : status };
}

/** The period: the printed label beside the published dates, kind and state, or the label and "unknown" only when
 * no dates are published. */
export function periodText(c: Pick<Claim, "period_label" | "period_kind" | "period_start" | "period_end" | "period_state">): string {
  const printed = c.period_label ? `${c.period_label} · ` : "";
  if (c.period_start !== null) return `${printed}${c.period_start}..${c.period_end} ${c.period_kind} (${c.period_state})`;
  return `${printed}unknown (${c.period_state})`;
}

/** The boundary with its entity wording and its state. */
export function boundaryText(c: Pick<Claim, "reporting_boundary" | "boundary_detail" | "boundary_state">): string {
  return `${c.reporting_boundary}${c.boundary_detail ? `: ${c.boundary_detail}` : ""} (${c.boundary_state})`;
}

export type Decision = "jump and highlight" | "jump only" | "do not navigate";

/** V3: a page in the document with a box is jumped to and highlighted, a page without a box is jumped to only,
 * and a missing or out-of-range page is not navigated to. */
export function decide(claim: Pick<Claim, "page" | "boxes">, pageCount: number): Decision {
  if (claim.page === null || !Number.isInteger(claim.page) || claim.page < 1 || claim.page > pageCount) {
    return "do not navigate";
  }
  return claim.boxes && claim.boxes.length > 0 ? "jump and highlight" : "jump only";
}

/** Ids for the requests of one kind of selection: only the newest is current, so an answer that arrives late
 * for an earlier selection is dropped instead of replacing the newer one. */
export function newestOnly() {
  let last = 0;
  return { start: () => ++last, isCurrent: (id: number) => id === last };
}

/** The boxes belong to one page image: draw them only once that very image (same document, page and scale)
 * has loaded. */
export function overlayShown(loadedSrc: string | null, src: string): boolean {
  return loadedSrc === src;
}

/** The page after a left (-1) or right (+1) arrow, kept within 1..pageCount. */
export function stepPage(page: number, delta: number, pageCount: number): number {
  return Math.min(Math.max(page + delta, 1), Math.max(pageCount, 1));
}

/** The claim index after an up (-1) or down (+1) arrow; -1 means none selected, and an empty list stays at -1. */
export function stepClaim(index: number, delta: number, length: number): number {
  if (length === 0) return -1;
  if (index < 0) return delta > 0 ? 0 : length - 1;
  return Math.min(Math.max(index + delta, 0), length - 1);
}
