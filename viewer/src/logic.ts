// Pure viewer logic, tested with `node --test` (Node strips the types): no imports, no enums.

export type Box = [number, number, number, number]; // x0, top, x1, bottom in PDF points, top-left origin

export type Claim = {
  id: number;
  locator: string;
  metric_text: string | null;
  value_text: string;
  unit_text: string | null;
  period_label: string | null;
  reporting_boundary: string;
  boundary_detail: string | null;
  page: number | null; // the evidence page; null when the evidence is not on a page
  boxes: Box[] | null;
  source_match: "matched" | "cited" | "unresolved" | null; // null: no source-match row yet
  source_match_reason: string | null;
};

export type Label = { status: "matched" | "cited" | "unresolved" | null; text: string };

export const NOT_CHECKED = "not checked: run gct link";

/** The source-match label: three statuses with their reason as stored, and a plain line when not checked. */
export function label(status: Claim["source_match"], reason: string | null): Label {
  if (status === null) return { status: null, text: NOT_CHECKED };
  return { status, text: reason ? `${status}: ${reason}` : status };
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
