// Pure logic of story 6.4 part B (transfer rules and reason texts, the chip, the saved-view form, the guided question
// counts), tested with `node --test` (Node strips the types): only records.ts is imported.
import { CHOICES, type Filter, type Selection } from "./records.ts";

export type Tab = "tables" | "graphs";
/** What a tab body reports through onSelectionChange; 6.3 adds a kind that has no selection type (S5b). */
export type Sent = Selection | { type: "none"; kind: string } | null;
/** A transferred selection, shown in the receiving tab with its words; never stored. */
export type Chip = { selection: Selection; text: string };

export const GRAPH_LIMIT = 500; // E6-D3

function claims(n: number): string {
  return n === 1 ? "1 claim" : `${n.toLocaleString("en-US")} claims`;
}

export function rowsButton(n: number): string {
  return n === 1 ? "Show 1 row in Graphs" : `Show ${n.toLocaleString("en-US")} rows in Graphs`;
}

export function claimsButton(n: number): string {
  return `Show ${claims(n)} in Tables`;
}

export const SERIES_FROM_TABLES = "Show as a time series";
export const SERIES_FROM_GRAPHS = "Show this series in Tables";
export const NONE_IN_TABLES = "Select rows to show them in Graphs.";
export const NONE_IN_GRAPHS = "Select claims or a series to show them in Tables.";

export function limitText(n: number): string {
  return `${n.toLocaleString("en-US")} rows selected; a graph draws at most ${GRAPH_LIMIT}. Select fewer.`;
}

/** The 6.1 F2 refusal of a stale pin, with its next step. */
export function staleText(was: number, now: number): string {
  return `Data version ${was} is no longer the current one; the current version is ${now}. Reload to see version ${now}.`;
}

/** A picked graph element with no rows of its own, named in plain words (graphs.ts WORDS). */
export function kindText(kind: string): string {
  return `${/^[aeiou]/i.test(kind) ? "An" : "A"} ${kind} has no rows of its own; select claims or a series.`;
}

type Button = { label: string; enabled: boolean };
export type Bar = { claims: Button; series: Button; reason: string | null };

/** The transfer bar of a tab: its two buttons and the one reason line (B1, D10). The time series asked from Tables is
 * decided by the server's series shape when pressed (the 6.1 F3 texts), since the rows' series are not on the page. */
export function bar(from: Tab, sent: Sent, pinned: number, newer: number | null): Bar {
  const n = sent?.type === "claims" ? sent.claim_ids.length : 0;
  const label = { claims: from === "tables" ? rowsButton(n) : claimsButton(n),
    series: from === "tables" ? SERIES_FROM_TABLES : SERIES_FROM_GRAPHS };
  const out = (c: boolean, s: boolean, reason: string | null): Bar =>
    ({ claims: { label: label.claims, enabled: c }, series: { label: label.series, enabled: s }, reason });
  if (sent === null) return out(false, false, from === "tables" ? NONE_IN_TABLES : NONE_IN_GRAPHS);
  if (sent.type === "none") return out(false, false, kindText(sent.kind));
  if (newer !== null || sent.data_version !== pinned) return out(false, false, staleText(sent.data_version, newer ?? pinned));
  if (sent.type === "series") return out(false, true, null);
  if (from === "graphs") return out(true, false, null);
  return n > GRAPH_LIMIT ? out(false, true, limitText(n)) : out(true, true, null);
}

const METRIC = new Map(CHOICES.metric);

/** A series' name for people: its label, or its metric in words, never a stored key. */
export function seriesLabel(s: { id: string; label: string | null; metric_key?: string | null }): string {
  const l = s.label ?? s.metric_key ?? null;
  return l === null ? `series ${s.id}` : METRIC.get(l) ?? l;
}

export function chipText(s: Selection, from: string, label = ""): string {
  return s.type === "claims" ? `${claims(s.claim_ids.length)} from ${from}` : `Time series: ${label} from ${from}`;
}

/** The answer of the series shape (F3) asked before a time-series transfer. */
export type SeriesAnswer = { data_version: number; drawable: boolean; reason: string | null;
  series: { id: string; label: string | null; metric_key: string | null } | null };

/** The chip a time-series transfer hands over, or the server's reason when the claims are in no series or in several. */
export function seriesChip(a: SeriesAnswer, filter: Filter, from: string): Chip | string {
  if (!a.drawable || a.series === null) return a.reason ?? "These claims are in no series.";
  const selection: Selection = { type: "series", series_id: a.series.id, filter, data_version: a.data_version };
  return { selection, text: chipText(selection, from, seriesLabel(a.series)) };
}

export function removeLabel(chip: string): string {
  return `Remove the selection: ${chip}`;
}

// The saved-view form (B2). The server checks the name and the key; these only say what it will do.
export const KEPT_FILTER = "The selection is not part of a saved view; a saved view keeps the filter.";
export const NO_VIEWS = "No saved views yet. Save the current filter below to come back to it.";

export function existsText(name: string): string {
  return `A view named ${name.trim()} exists. Saving puts this one first and keeps the earlier one.`;
}

export function exists(name: string, names: string[]): boolean {
  return names.includes(name.trim());
}

export function ready(name: string, key: string): boolean {
  return name.trim() !== "" && key.trim() !== "";
}

export function savedText(view: { section: string; saved_at: string; contributor: string }): string {
  return `${view.section === "graphs" ? "Graphs" : "Tables"} · saved ${view.saved_at.slice(0, 10)} by ${view.contributor}`;
}

export function savedLine(name: string): string {
  return `Saved ${name}.`;
}

export function removedLine(name: string): string {
  return `Removed ${name}. Its record stays in the workspace.`;
}

// The guided questions (B3, A4).
export const SERIES_QUESTION = "metric-over-time";
export type Question = { key: string; text: string; filter: Filter; section: Tab; matched: number;
  choices: { series: string; company: string; label: string | null; periods: number; filter: Filter }[] };

/** A question's count: the claims its filter matches, or for metric-over-time the number of its choices. */
export function questionCount(q: Question, version: number): string {
  if (q.key === SERIES_QUESTION) return `${q.choices.length} series with two or more periods`;
  return `${claims(q.matched)} in data version ${version}`;
}

export function choiceText(c: Question["choices"][number]): string {
  return `${c.company}: ${seriesLabel({ id: c.series, label: c.label })}, ${c.periods} periods`;
}

/** A metric-over-time choice opens Graphs on its series: the filter names the series and a series selection asks the
 * series shape, so the chip says where it came from. */
export function choiceChip(c: Question["choices"][number], version: number): Chip {
  const selection: Selection = { type: "series", series_id: c.series, filter: c.filter, data_version: version };
  return { selection, text: chipText(selection, "Questions", seriesLabel({ id: c.series, label: c.label })) };
}

export const NO_CHOICES ="No series has two or more periods in this data version.";
