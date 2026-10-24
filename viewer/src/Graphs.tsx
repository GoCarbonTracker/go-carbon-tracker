import { useEffect, useMemo, useRef, useState } from "react";
import type { Core, LayoutOptions, NodeSingular, StylesheetJson } from "cytoscape";
import { newestOnly } from "./logic.ts";
import { type BodyProps, CHOICES, countText, isStale, recordsBody, type Selection, seriesText } from "./records.ts";
import { canvasLabel, degrees, documentNames, edgeName, elements, type GraphAnswer, hyperedgeRows, hypergraph, type Item, layoutOf,
  LEGEND, neighbourhood, opening, picked, pointRow, relationText, request, type Row, type SeriesAnswer, sideText, type Target,
  timeSeries, type View, VIEWS } from "./graphs.ts";
import "./graphs.css";

type Failure = { cause: string; next_action: string };
type Answer = { key: string; view: View } & ({ shape: "graph"; data: GraphAnswer } | { shape: "series"; data: SeriesAnswer });
type Props = Omit<BodyProps, "onSelectionChange"> & {
  // S5b: the F6 selection of the picked elements, or a kind that has none (6.4 part B wires it)
  onSelectionChange?: (s: Selection | { type: "none"; kind: string } | null) => void;
  onStale?: () => void; // F11 i1: a stale-version 409; the shell checks the version and shows its notice
};

const METRIC_WORDS = Object.fromEntries(CHOICES.metric);

// A drawing is fitted to the canvas but never enlarged past this zoom, so a few nodes keep their labels in proportion.
const MAX_FIT = 1.25;

// Node kinds by shape (and by the word in their tables), never by colour alone; one accent marks the selection. A
// label is one line, cut short, drawn only above zoom 1 (Cytoscape checks min-zoomed-font-size at power-of-two zoom
// steps), so a large drawing shows its shapes until zoomed in; a node under the pointer or selected shows its whole
// label at about 12 px above the others. Every label is in full in the tables. Edges are long enough for the labels.
const STYLE: StylesheetJson = [
  { selector: "node", style: { shape: "ellipse", width: 18, height: 18, "background-color": "#fff", "border-width": 1.5,
    "border-color": "#1d2126", label: (n: NodeSingular) => n.data("label").split("\n")[0], "font-size": 10,
    color: "#1d2126", "text-wrap": "ellipsis", "text-max-width": "100px", "text-valign": "bottom", "text-margin-y": 3,
    "min-zoomed-font-size": 6 } },
  { selector: "node.point", style: { label: "data(label)", "text-wrap": "wrap", "text-max-width": "160px" } },
  { selector: "node.hover, node:selected", style: { label: "data(label)", "text-wrap": "wrap", "min-zoomed-font-size": 0,
    "z-index": 10,
    "font-size": (n: NodeSingular) => Math.max(10, 12 / n.cy().zoom()),
    "text-max-width": (n: NodeSingular) => `${Math.max(200, 240 / n.cy().zoom())}px`,
    "text-background-color": "#fff", "text-background-opacity": 0.9, "text-background-padding": "2px" } },
  { selector: "node.page, node.cell", style: { shape: "rectangle" } },
  { selector: "node.period", style: { shape: "round-rectangle", width: 28 } },
  { selector: "node.boundary", style: { shape: "hexagon", width: 22 } },
  { selector: "node.series", style: { shape: "diamond", width: 22, height: 22 } },
  { selector: "node.company, node.auditor, node.flag, node.highlight", style: { shape: "triangle" } },
  { selector: "node.adjudication", style: { shape: "pentagon", width: 22, height: 22 } },
  { selector: "node.hub", style: { width: 6, height: 6, "background-color": "#5b626b", "border-width": 0 } },
  { selector: "edge", style: { width: 1, "line-color": "#c2c6cc", "curve-style": "straight" } },
  { selector: "edge.comparison", style: { width: 2, "line-color": "#5b626b", label: "data(label)", "font-size": 10,
    "min-zoomed-font-size": 6, "text-background-color": "#fff", "text-background-opacity": 1, "text-background-padding": "1px" } },
  { selector: "edge.unresolved", style: { "line-style": "dashed" } },
  { selector: "edge.not-compared", style: { "line-style": "dotted" } },
  { selector: "node:selected", style: { "border-color": "#0a6e8a", "border-width": 3 } },
  { selector: "node.hub:selected", style: { "background-color": "#0a6e8a", width: 10, height: 10 } },
  { selector: "edge:selected", style: { "line-color": "#0a6e8a", width: 3 } },
];

// F11 i4: the tab's own same-origin read of the records endpoint.
async function post(body: object): Promise<{ status: number; data: any }> {
  const r = await fetch("/api/records", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  return { status: r.status, data: await r.json() };
}

async function pagesOf(document: number): Promise<number> {
  const r = await fetch(`/api/documents/${document}`, { headers: { Accept: "application/json" } });
  const data = await r.json();
  if (!r.ok) throw data as Failure;
  return data.pages.length;
}

/** The Graphs tab (story 6.3): the claims of one records answer as a neighbourhood graph, a hypergraph or a time
 * series, every node and edge also in a table. It reads only: nodes can be selected and dragged, nothing is written.
 * Cytoscape is imported when the tab is first shown, so the Evidence section never loads it. */
export default function Graphs({ filter, dataVersion, openEvidence, selection, onSelectionChange, onStale }: Props) {
  const [view, setView] = useState<View>("neighbourhood");
  const [visible, setVisible] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [stale, setStale] = useState(false);
  const [chosen, setChosen] = useState<string[]>([]);
  const [said, setSaid] = useState<string | null>(null);
  const [choice, setChoice] = useState<{ label: string; targets: { text: string; target: Target }[] } | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const spaced = useRef(false); // Space has picked on the rows since the last drawing or mouse click on a row
  const opener = useRef<HTMLElement | null>(null); // the row that opened a page, focused again on return
  const requests = useRef(newestOnly()).current;
  const pageCounts = useRef(new Map<number, number>()).current;

  const shown = selection?.type === "series" ? "series" : view;
  const asked = request(filter, shown, selection);
  const body = { ...recordsBody(asked.filter, dataVersion, asked.shape), ...(asked.claim_ids ? { claim_ids: asked.claim_ids } : {}) };
  const key = JSON.stringify(body);
  const pending = visible && answer?.key !== key && !failure && !stale;

  // The tab body stays mounted while hidden; it asks and draws only while shown, so a hidden canvas is never laid out.
  useEffect(() => {
    const watch = new ResizeObserver(([e]) => setVisible(e.contentRect.width > 0));
    watch.observe(root.current!);
    return () => watch.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    cy.current?.resize();
    if (opener.current) {
      opener.current.focus();
      opener.current = null;
    }
  }, [visible]);

  useEffect(() => {
    if (!visible || answer?.key === key) return;
    const id = requests.start();
    setFailure(null);
    setStale(false);
    setSaid(null);
    setChoice(null);
    // The drawing on screen stays, labelled with its own version, until the newest answer replaces it.
    post(body).then(
      ({ status, data }) => {
        if (!requests.isCurrent(id)) return; // a newer filter or view was asked meanwhile
        if (status === 200) setAnswer({ key, view: shown, shape: asked.shape, data } as Answer);
        else if (isStale(status, data.cause)) {
          setStale(true); // F11 i1: the shell's notice offers the new version; nothing of it is drawn
          onStale?.();
        } else setFailure(data);
      },
      (e) => requests.isCurrent(id) && setFailure({ cause: String(e), next_action: "Reload the page." }),
    );
  }, [visible, key]);

  // The two graph views draw from one answer; while another view's answer is asked, the drawing on screen stays.
  const drawnView = answer?.shape === "graph" && shown !== "series" ? shown : answer?.view;
  // After a refused request the drawing on screen stays, and the pressed view is the one drawn.
  const pressed = answer && (stale || failure) ? drawnView : shown;
  const items = useMemo(() => {
    if (!answer?.data.drawable) return [];
    if (answer.shape === "series") return timeSeries(answer.data);
    return drawnView === "hypergraph" ? hypergraph(answer.data, METRIC_WORDS) : neighbourhood(answer.data, METRIC_WORDS);
  }, [answer, drawnView]);
  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);
  const names = useMemo(() => {
    if (!answer) return new Map<number, string>();
    const rows: Row[] = answer.shape === "series" ? answer.data.points : answer.data.nodes.flatMap((n) => (n.row ? [n.row] : []));
    return documentNames(rows);
  }, [answer]);

  const open = (i: Item) => {
    const o = opening(i, names);
    setSaid(null);
    setChoice(null);
    if (o.say) setSaid(`${i.label || i.word}: ${o.say}`);
    else if (o.targets.length === 1) go(o.targets[0].target);
    else setChoice({ label: i.label || i.word, targets: o.targets });
  };

  // F11 i3: a page outside its document opens nothing; a failure to open is shown in the Evidence section (i2).
  const go = async (t: Target) => {
    if (!t.sheet) {
      const was = document.activeElement as HTMLElement | null;
      let pages = pageCounts.get(t.document);
      if (pages === undefined) {
        try {
          pages = await pagesOf(t.document);
        } catch (e) {
          return setFailure(e instanceof Error ? { cause: String(e), next_action: "Reload the page." } : (e as Failure));
        }
        pageCounts.set(t.document, pages);
      }
      if (!t.page || t.page < 1 || t.page > pages) return setSaid("This claim has no source location to open.");
      opener.current = was; // a page switches to Evidence; on return the focus goes back here
    }
    openEvidence(t);
  };

  const rowOf = (id: string) => root.current?.querySelector<HTMLElement>(`[data-el="${CSS.escape(id)}"]`) ?? null;

  // Draw the items; Cytoscape is loaded on the first drawing. Tapping selects (Shift adds), a double-click opens.
  useEffect(() => {
    if (items.length === 0) {
      cy.current?.destroy();
      cy.current = null;
      return;
    }
    let live = true;
    setChosen([]);
    spaced.current = false;
    import("cytoscape").then(({ default: cytoscape }) => {
      if (!live || !canvas.current) return;
      cy.current?.destroy();
      const c = cytoscape({ container: canvas.current, elements: elements(items), style: STYLE, boxSelectionEnabled: false,
        // cose: edges long enough that a few nodes' one-line labels do not run into each other (H1, H5, measured on
        // the Tata copy: 10 nodes fit at zoom 1.25 with labels apart; 165 nodes fit at about 0.4, shapes only)
        layout: { name: layoutOf(drawnView!, items), animate: false, idealEdgeLength: 90, nodeRepulsion: 20000 } as LayoutOptions,
        wheelSensitivity: 0.3 });
      if (c.zoom() > MAX_FIT) {
        c.zoom(MAX_FIT);
        c.center();
      }
      c.on("select unselect", () => setChosen(c.$(":selected").map((e) => e.id())));
      c.on("mouseover", "node", (e) => e.target.addClass("hover"));
      c.on("mouseout", "node", (e) => e.target.removeClass("hover"));
      c.on("zoom", () => c.$("node.hover, node:selected").nonempty() && c.style().update()); // their label size follows
      c.on("tap", "node, edge", (e) => rowOf(e.target.id())?.scrollIntoView({ block: "nearest" }));
      c.on("dbltap", "node, edge", (e) => open(byId.get(e.target.id())!));
      cy.current = c;
    });
    return () => {
      live = false;
    };
  }, [items]);

  useEffect(() => () => cy.current?.destroy(), []);

  // S5b: the selection of the picked elements goes to the shell (6.4 part B wires it).
  useEffect(() => {
    if (!onSelectionChange || !answer) return;
    const p = picked(chosen.map((id) => byId.get(id)!).filter(Boolean));
    if (p === null || p.type === "none") onSelectionChange(p);
    else onSelectionChange({ ...p, filter, data_version: answer.data.data_version });
  }, [chosen]);

  const pick = (id: string) => {
    const c = cy.current;
    if (!c || (chosen.length === 1 && chosen[0] === id)) return;
    c.$(":selected").unselect();
    c.$id(id).select();
  };

  // The first Space keeps what focus picked; later ones add or drop the row's element, and focus then picks nothing.
  const toggle = (id: string) => {
    const e = cy.current?.$id(id);
    if (!e) return;
    if (!spaced.current) {
      spaced.current = true;
      e.select();
    } else e.selected() ? e.unselect() : e.select();
  };

  // A row's button: focus or click selects its element, Enter or click opens its source, Space adds it to the picked.
  const rowButton = (i: Item, text?: string, name?: string) => (
    <button type="button" className={chosen.includes(i.id) ? "link picked" : "link"} data-el={i.id} aria-label={name}
      onFocus={() => spaced.current || pick(i.id)}
      onClick={(e) => {
        if (e.detail > 0) { // a mouse click picks this one alone; Enter keeps what Space picked
          spaced.current = false;
          pick(i.id);
        }
        open(i);
      }}
      onKeyDown={(e) => {
        if (e.key === " ") {
          e.preventDefault();
          toggle(i.id);
        }
      }}>
      {text ?? (i.label || i.word)}
    </button>
  );

  const data = answer?.data;
  const drawn = items.length > 0 && data;
  const claims = drawn ? items.filter((i) => i.kind === "claim" || i.kind === "point").length : 0;

  return (
    <div className="graphs" ref={root} onFocus={(e) => {
      // Focus put anywhere in the tab now is where the person is: a page opened earlier no longer takes it back, also
      // when a hide and a show of the tab fell in one ResizeObserver report and the return above never ran.
      if (e.target !== opener.current) opener.current = null;
    }}>
      <div className="graph-views" role="group" aria-label="Graph view">
        {VIEWS.map(([v, words]) => (
          <button key={v} type="button" aria-pressed={pressed === v} onClick={() => setView(v)}
            disabled={selection?.type === "series" && v !== "series"}>{words}</button>
        ))}
      </div>
      <p className="legend">{LEGEND}</p>
      {failure && <p className="problem" role="alert">{failure.cause} {failure.next_action}</p>}
      {pending && <p className="hint">Reading the claims of data version {dataVersion}.</p>}
      {data && <p className="graph-count">{countText(data.matched, data.data_version)}</p>}
      {data && !data.drawable && data.matched > 0 && <p className="graph-reason">{data.reason}</p>}
      {drawn && (
        <>
          <div className="canvas" ref={canvas} role="img" aria-label={canvasLabel(claims, data.data_version)} aria-busy={pending} />
          <div aria-live="polite">
            {said && <p className="graph-said">{said}</p>}
            {choice && (
              <div className="graph-choice" role="group" aria-label={`Open a source of ${choice.label}`}>
                <span>Open a source of {choice.label}:</span>
                {choice.targets.map((t) => (
                  <button key={t.text} type="button" className="link" onClick={() => go(t.target)}>{t.text}</button>
                ))}
              </div>
            )}
          </div>
          {answer.shape === "graph" && drawnView === "neighbourhood" && <NodesAndEdges items={items} rowButton={rowButton} byId={byId} />}
          {answer.shape === "graph" && drawnView === "hypergraph" && (
            <table className="graph-table">
              <caption>Hyperedges: each hub joins one claim to the items it is linked to</caption>
              <thead><tr><th scope="col">Claim (its hub)</th><th scope="col">Members</th><th scope="col">Compared with</th></tr></thead>
              <tbody>
                {hyperedgeRows(answer.data, items).map((h) => (
                  <tr key={h.hub.id}>
                    <th scope="row">{rowButton(h.hub, h.claim.label)}<Notes item={h.claim} /></th>
                    <td><ul>{h.members.map((m) => <li key={m.id}>{m.word}: {rowButton(m)}<Notes item={m} /></li>)}</ul></td>
                    <td><ul>{h.compared.flatMap((c) => c.edges.map((e) => (
                      <li key={e.id}>{rowButton(e, `${e.label}: ${c.claim.label}`)}</li>
                    )))}</ul></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {answer.shape === "series" && (
            <>
              <table className="graph-table">
                <caption>Points of {answer.data.series ? seriesText({ ...answer.data.series, company_id: 0,
                  points: answer.data.points.length }, answer.data.series.company_name) : "this series"}</caption>
                <thead><tr><th scope="col">Period</th><th scope="col">Value and unit as printed</th>
                  <th scope="col">Document</th><th scope="col">Page</th><th scope="col">Comparable</th></tr></thead>
                <tbody>
                  {answer.data.points.map((p) => {
                    const i = byId.get(`point:${p.claim.id}`)!;
                    const r = pointRow(p);
                    return (
                      <tr key={i.id}>
                        <th scope="row">{rowButton(i, r.period)}</th><td>{r.value}</td><td>{r.document}</td><td>{r.where}</td>
                        <td>{r.comparable}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <table className="graph-table">
                <caption>Comparisons</caption>
                <thead><tr><th scope="col">Period</th><th scope="col">Side A</th><th scope="col">Side B</th>
                  <th scope="col">State</th></tr></thead>
                <tbody>
                  {answer.data.comparisons.length === 0 && <tr><td colSpan={4}>No comparisons among these points.</td></tr>}
                  {answer.data.comparisons.map((c) => {
                    const i = byId.get(`comparison:${c.claim_a}:${c.claim_b}`)!;
                    const side = (id: number) => sideText(answer.data.points.find((p) => p.claim.id === id));
                    return (
                      <tr key={i.id}>
                        <th scope="row">{rowButton(i, pointRow(answer.data.points.find((p) => p.claim.id === c.claim_a)!).period)}</th>
                        <td>{side(c.claim_a)}</td><td>{side(c.claim_b)}</td><td>{i.label}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </div>
  );
}

function Notes({ item }: { item: Item }) {
  return item.notes.length > 0 ? <span className="notes">{item.notes.join("; ")}</span> : null;
}

function NodesAndEdges({ items, rowButton, byId }: { items: Item[];
  rowButton: (i: Item, text?: string, name?: string) => JSX.Element; byId: Map<string, Item> }) {
  const edgesAt = degrees(items);
  return (
    <>
      <table className="graph-table">
        <caption>Nodes</caption>
        <thead><tr><th scope="col">Kind</th><th scope="col">Label</th><th scope="col">Edges</th></tr></thead>
        <tbody>
          {items.filter((i) => i.group === "nodes").map((i) => (
            <tr key={i.id}>
              <td>{i.word}</td><th scope="row">{rowButton(i)}<Notes item={i} /></th><td>{edgesAt.get(i.id) ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <table className="graph-table">
        <caption>Edges</caption>
        <thead><tr><th scope="col">From</th><th scope="col">Relation</th><th scope="col">To</th><th scope="col">State</th></tr></thead>
        <tbody>
          {items.filter((i) => i.group === "edges").map((i) => (
            <tr key={i.id}>
              <th scope="row">{rowButton(i, byId.get(i.source!)?.label, edgeName(i, byId))}</th>
              <td>{relationText(i)}</td>
              <td>{byId.get(i.target!)?.label}</td>
              <td>{i.state ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
