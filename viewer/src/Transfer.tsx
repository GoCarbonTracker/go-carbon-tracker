import { useEffect, useState } from "react";
import { recordsBody } from "./records.ts";
import { bar, type Chip, chipText, removeLabel, type SeriesAnswer, seriesChip, type Sent, type Tab } from "./transfer.ts";
import "./transfer.css";

type Failure = { cause: string; next_action: string };

const OTHER: Record<Tab, Tab> = { tables: "graphs", graphs: "tables" };
const WORDS: Record<Tab, string> = { tables: "Tables", graphs: "Graphs" };

/** The transfer bar above a tab body (story 6.4 B1): the tab's selection to the other tab, as claims or one time series,
 * or one line saying why not. The filter bar and the pinned version never change here. current() asks the server for
 * its current version first, so a selection of a version no longer current is refused before anything is sent. */
export function Transfer({ tab, sent, pinned, newer, current, onTransfer }: {
  tab: Tab; sent: Sent; pinned: number; newer: number | null; current: () => Promise<number | null>;
  onTransfer: (to: Tab, chip: Chip) => void;
}) {
  const [said, setSaid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setSaid(null), [sent, tab]);
  const b = bar(tab, sent, pinned, newer);

  const fresh = async () => {
    const now = await current().catch(() => pinned);
    return now === null || now === pinned;
  };

  const asClaims = async () => {
    if (sent?.type !== "claims" || !(await fresh())) return;
    onTransfer(OTHER[tab], { selection: sent, text: chipText(sent, WORDS[tab]) });
  };

  // The server decides the series (the 6.1 F3 texts): from rows, the one series of every claim; from a series node,
  // its label.
  const asSeries = async () => {
    if (sent === null || sent.type === "none") return;
    setBusy(true);
    setSaid(null);
    try {
      if (!(await fresh())) return;
      const body = sent.type === "claims"
        ? { ...recordsBody(sent.filter, pinned, "series"), claim_ids: sent.claim_ids }
        : recordsBody({ ...sent.filter, series: [sent.series_id] }, pinned, "series");
      const r = await fetch("/api/records", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) return setSaid(`${(data as Failure).cause} ${(data as Failure).next_action}`);
      const chip = seriesChip(data as SeriesAnswer, sent.filter, WORDS[tab]);
      if (typeof chip === "string") setSaid(chip);
      else onTransfer(OTHER[tab], chip);
    } catch (e) {
      setSaid(`${String(e)} Reload the page.`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="transfer" role="group" aria-label={`Show the selection of ${WORDS[tab]} in ${WORDS[OTHER[tab]]}`}>
      <div className="transfer-buttons">
        <button type="button" disabled={!b.claims.enabled || busy} onClick={asClaims}>{b.claims.label}</button>
        <button type="button" disabled={!b.series.enabled || busy} onClick={asSeries}>{b.series.label}</button>
      </div>
      <p className="transfer-reason" aria-live="polite">{said ?? b.reason}</p>
    </div>
  );
}

/** The chip of a transferred selection in the receiving tab: removing it shows the whole filter again. */
export function ChipLine({ chip, onRemove }: { chip: Chip; onRemove: () => void }) {
  return (
    <p className="chip">
      <span>{chip.text}</span>
      <button type="button" aria-label={removeLabel(chip.text)} onClick={onRemove}>Remove</button>
    </p>
  );
}
