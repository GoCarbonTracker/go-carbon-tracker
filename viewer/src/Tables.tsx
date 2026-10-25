import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { newestOnly, stepClaim } from "./logic.ts";
import { type BodyProps, isStale, recordsBody } from "./records.ts";
import { ariaSort, boundaryText, clearedText, COLUMNS, lastOffset, locationText, metricText, NO_LOCATION, nextSort, PAGE, pageState, periodText, request, type Row, rowsText, rowTarget, selectionOf, selectLabel, type Sort, togglePage, toggled, valueText } from "./tables.ts";
import "./tables.css";

type Failure = { cause: string; next_action: string };
type Answer = { data_version: number; matched: number; offset: number; rows: Row[]; sort: Sort };

function isR2(r: Row): boolean {
  const m = r.claim.metric_text || "";
  const v = r.claim.value_text || "";
  return m.length > 50 || m.startsWith("─") || m.includes("aim to") || m.includes("commit to") || m.includes("target for") || v === "";
}

async function call<T>(path: string, body?: object): Promise<{ status: number; data: T | Failure }> {
  const r = await fetch(path, body === undefined ? { headers: { Accept: "application/json" } } : {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  return { status: r.status, data: await r.json() };
}

/** The Tables tab (story 6.2): one page of 200 rows of the shared filter on the pinned version (F3 table shape), sorted
 * on the server by one column, with checked rows for 6.4 (F6) and each row opening its evidence (FR47). onStale asks
 * the shell to offer the newer version after a 409 on a stale pin (F2). */
export function Tables({ filter, dataVersion, openEvidence, selection, onSelectionChange, onStale }:
  BodyProps & { onStale?: () => void }) {
  const asked = request(filter, null, selection);
  const key = JSON.stringify([asked.filter, asked.extra, dataVersion]); // what the rows and the checks belong to
  const [sort, setSort] = useState<Sort>(null);
  const [at, setAt] = useState({ key, offset: 0 });
  if (at.key !== key) setAt({ key, offset: 0 }); // a filter or version change goes back to the first page, and stays
  const offset = at.key === key ? at.offset : 0;
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [said, setSaid] = useState({ text: "", n: 0 }); // n replaces the line, so the same words are read out again
  const say = (text: string) => setSaid((s) => ({ text, n: s.n + 1 }));
  const bar = JSON.stringify([filter, dataVersion]);
  const [checks, setChecks] = useState({ key, bar, version: dataVersion, ids: new Set<number>() });
  const [cleared, setCleared] = useState<string | null>(null);
  const [focus, setFocus] = useState(0);
  const rowEls = useRef<(HTMLTableRowElement | null)[]>([]);
  const pagingEls = useRef<Record<string, HTMLButtonElement | null>>({});
  const headBox = useRef<HTMLInputElement>(null);
  const requests = useRef(newestOnly()).current;
  const sent = useRef("null");

  // Checks hold for one filter and one version (T6): another one clears them, with a line when any were checked. A
  // selection transferred in or removed (6.4 B1) clears them too, without a line: the chip says what is shown.
  if (checks.key !== key) {
    const why = checks.version !== dataVersion ? "version" : checks.bar !== bar ? "filter" : null;
    setCleared(checks.ids.size && why ? clearedText(why, dataVersion) : null);
    setChecks({ key, bar, version: dataVersion, ids: new Set() });
  }
  const chosen = checks.key === key ? checks.ids : new Set<number>();

  useEffect(() => {
    const id = requests.start();
    setBusy(true);
    setFailure(null);
    const body = { ...recordsBody(asked.filter, dataVersion, "table", offset, PAGE), ...request(filter, sort, selection).extra };
    const sorted = sort;
    call<Answer>("/api/records", body).then(({ status, data }) => {
      if (!requests.isCurrent(id)) return; // a later page, sort or filter was asked for meanwhile (NFR1)
      setBusy(false);
      if (status === 200) {
        setAnswer({ ...(data as Answer), sort: sorted }); // the header states the order of the rows on screen
        setFocus(0);
      } else if (isStale(status, (data as Failure).cause) && onStale) {
        onStale(); // 6.1 F11 i1: the rows on screen stay, labelled with their version
      } else setFailure(data as Failure);
    }, (e) => {
      if (!requests.isCurrent(id)) return;
      setBusy(false);
      setFailure({ cause: String(e), next_action: "Reload the page." });
    });
  }, [key, offset, sort?.key, sort?.dir]);

  useEffect(() => {
    const s = selectionOf(chosen, filter, dataVersion);
    if (JSON.stringify(s) === sent.current) return;
    sent.current = JSON.stringify(s);
    onSelectionChange?.(s);
  }, [checks]);

  const rows = answer?.rows ?? [];
  const ids = rows.map((r) => r.claim.id);
  const state = pageState(chosen, ids);
  useEffect(() => {
    if (headBox.current) headBox.current.indeterminate = state === "some";
  }, [state]);

  // When the button that was pressed becomes disabled at the first or last page, focus goes to the one beside it.
  const matched = answer?.matched ?? 0;
  const atStart = !answer || answer.offset === 0;
  const atEnd = !answer || answer.offset + PAGE >= matched;
  useEffect(() => {
    const now = document.activeElement as HTMLButtonElement | null;
    if (!now?.disabled || !Object.values(pagingEls.current).includes(now)) return;
    (atEnd ? pagingEls.current.Previous : pagingEls.current.Next)?.focus();
  }, [answer]);

  const check = (next: Set<number>) => {
    setCleared(null);
    setChecks({ key, bar, version: dataVersion, ids: next });
  };
  const goTo = (to: number) => setAt({ key, offset: to });

  const open = async (r: Row) => {
    say("");
    setFailure(null);
    const l = r.evidence.location;
    let pages = 0;
    if (l.resolved && l.sheet === null && l.page !== null) {
      const { status, data } = await call<{ pages: unknown[] }>(`/api/documents/${l.document}`)
        .catch((e) => ({ status: 0, data: { cause: String(e), next_action: "Reload the page." } }));
      if (status !== 200) return setFailure(data as Failure);
      pages = (data as { pages: unknown[] }).pages.length;
    }
    const t = rowTarget(r, pages);
    if (t) openEvidence(t);
    else say(NO_LOCATION);
  };

  const onKey = (e: KeyboardEvent, i: number) => {
    if (e.target !== rowEls.current[i] || !["ArrowUp", "ArrowDown", "Enter", " "].includes(e.key)) return;
    e.preventDefault();
    e.stopPropagation(); // the Evidence section's arrows never see these keys
    if (e.key === "Enter") open(rows[i]);
    else if (e.key === " ") check(toggled(chosen, rows[i].claim.id));
    else {
      const to = stepClaim(i, e.key === "ArrowUp" ? -1 : 1, rows.length);
      setFocus(to);
      rowEls.current[to]?.focus();
    }
  };

  if (!answer) {
    return failure ? <p className="problem" role="alert">{failure.cause} {failure.next_action}</p>
      : <p className="hint">Reading the rows of data version {dataVersion}.</p>;
  }
  return (
    <div className="tables">
      {failure && <p className="problem" role="alert">{failure.cause} {failure.next_action}</p>}
      <p className="tables-said" aria-live="polite"><span key={said.n}>{said.text}</span></p>
      {cleared && <p className="meta" role="status">{cleared}</p>}
      {answer.matched > 0 && (
        <>
          <div className="selection-count">
            <span>{chosen.size.toLocaleString("en-US")} selected</span>
            {chosen.size > 0 && <button type="button" onClick={() => check(new Set())}>Clear selection</button>}
          </div>
          <table className="claims-table" aria-busy={busy}>
            <caption>Claims matching the filter in published data version {answer.data_version}</caption>
            <thead>
              <tr>
                <th scope="col" className="select">
                  <input type="checkbox" className="select-page" ref={headBox} aria-label="Select all rows on this page"
                    checked={state === "all"} onChange={() => check(togglePage(chosen, ids))} />
                </th>
                {COLUMNS.map((c) => (
                  <th key={c.name} scope="col" aria-sort={ariaSort(answer.sort, c.key)} className={c.key === "value" ? "num" : undefined}>
                    {c.key === null ? c.name : (
                      <button type="button" className="sort" onClick={() => {
                        setSort(nextSort(answer.sort, c.key!));
                        goTo(0);
                      }}>
                        {c.name}
                        <span className="arrow" aria-hidden="true">{answer.sort?.key === c.key ? (answer.sort.dir === "asc" ? "▲" : "▼") : ""}</span>
                      </button>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const cells = [r.company_name, r.document_name];
                const rest = [periodText(r), boundaryText(r), r.evidence.text, r.review.text, r.claim.claim_state];
                return (
                  <tr key={r.claim.id} className={chosen.has(r.claim.id) ? "claim-row checked" : "claim-row"}
                    tabIndex={i === focus ? 0 : -1} ref={(el) => (rowEls.current[i] = el)} onFocus={() => setFocus(i)}
                    onKeyDown={(e) => onKey(e, i)}>
                    <td className="select">
                      <input type="checkbox" className="select-row" tabIndex={-1} aria-label={selectLabel(r)}
                        checked={chosen.has(r.claim.id)} onChange={() => check(toggled(chosen, r.claim.id))} />
                    </td>
                    {cells.map((t, j) => <td key={j} title={t}><div className="clamp">{t}</div></td>)}
                    <td>
                      <button type="button" className="link" tabIndex={-1} onClick={() => open(r)}>{locationText(r)}</button>
                    </td>
                    <td title={metricText(r)}>
                      <div className="clamp">
                        <span className={isR2(r) ? "pill-badge r2-pill" : "pill-badge r1-pill"}>
                          {isR2(r) ? "R2 Qualitative" : "R1 Table"}
                        </span>
                        {metricText(r)}
                      </div>
                    </td>
                    <td className="num">{valueText(r)}</td>
                    {rest.map((t, j) => <td key={j} title={t}><div className="clamp">{t}</div></td>)}
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="tables-paging">
            {([["First", 0, atStart], ["Previous", answer.offset - PAGE, atStart], ["Next", answer.offset + PAGE, atEnd],
              ["Last", lastOffset(matched), atEnd]] as const).map(([word, to, off]) => (
              <button key={word} type="button" disabled={off} ref={(el) => (pagingEls.current[word] = el)}
                onClick={() => goTo(to)}>{word}</button>
            ))}
            <span aria-live="polite">{rowsText(answer.offset, rows.length, matched)}</span>
          </div>
        </>
      )}
    </div>
  );
}
