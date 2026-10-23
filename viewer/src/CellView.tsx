import { useEffect, useRef, useState } from "react";
import { cellPath, type EvidenceTarget } from "./records.ts";

type Cells = { name: string; sheet: string; cell: string; columns: string[]; header: string[]; row: number;
  cells: string[]; column: number };
type Failure = { cause: string; next_action: string };

/** A spreadsheet claim's evidence (F10): the sheet's header row and the claim's row, its cell marked. A panel in the
 * Tables and Graphs area; Escape or Close shuts it and focus goes back to what opened it. */
export function CellView({ target, pinned, onClose }: { target: EvidenceTarget; pinned: number; onClose: () => void }) {
  const [cells, setCells] = useState<Cells | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const panel = useRef<HTMLElement>(null);
  const opener = useRef(document.activeElement as HTMLElement | null);

  useEffect(() => {
    let live = true;
    (async () => {
      const r = await fetch(cellPath(target, pinned), { headers: { Accept: "application/json" } });
      const data = await r.json();
      if (!live) return;
      if (r.ok) setCells(data);
      else setFailure(data);
    })().catch((e) => live && setFailure({ cause: String(e), next_action: "Reload the page." }));
    return () => {
      live = false;
    };
  }, [target, pinned]);

  useEffect(() => {
    panel.current?.focus();
    const back = opener.current;
    return () => back?.focus();
  }, []);

  return (
    <section className="cell-view" aria-label="Cell evidence" tabIndex={-1} ref={panel}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}>
      <div className="cell-view-head">
        <h2>
          {cells ? `${cells.name}, sheet ${cells.sheet}, cell ${cells.cell}` : `Sheet ${target.sheet}, cell ${target.cell}`}
        </h2>
        <button type="button" onClick={onClose}>Close</button>
      </div>
      {!cells && !failure && <p className="hint">Reading the sheet.</p>}
      {failure && (
        <p className="problem" role="alert">
          {failure.cause} {failure.next_action}
        </p>
      )}
      {cells && (
        <div className="cell-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col"></th>
                {cells.columns.map((c, i) => <th key={c} scope="col" className={i === cells.column ? "marked" : undefined}>{c}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">1</th>
                {cells.header.map((v, i) => (
                  <td key={i} className={cells.row === 1 && i === cells.column ? "marked" : undefined}>{v}</td>
                ))}
              </tr>
              {cells.row !== 1 && (
                <tr>
                  <th scope="row">{cells.row}</th>
                  {cells.cells.map((v, i) => (
                    <td key={i} className={i === cells.column ? "marked" : undefined}
                      aria-current={i === cells.column ? "true" : undefined}>{v}</td>
                  ))}
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
