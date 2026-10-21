import { useCallback, useEffect, useRef, useState } from "react";
import { boundaryText, decide, label, newestOnly, overlayShown, periodText, stepClaim, stepPage, type Claim } from "./logic.ts";

type Company = { id: number; name: string; documents: Doc[] };
type Doc = { id: number; logical_name: string; version: number; file_type: string };
// pdfplumber's page frame, the space of the stored boxes: it need not start at 0, 0.
type PageSize = { left: number; top: number; width: number; height: number };
type Opened = { id: number; name: string; pages: PageSize[] };
type Failure = { cause: string; next_action: string };

class ApiError extends Error {
  failure: Failure;
  constructor(failure: Failure) {
    super(failure.cause);
    this.failure = failure;
  }
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  const data = await r.json();
  if (!r.ok) throw new ApiError(data);
  return data as T;
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
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  const docRequests = useRef(newestOnly()).current;

  useEffect(() => {
    (async () => {
      try {
        setHealth(await get("/api/health"));
        const { companies } = await get<{ companies: { id: number; name: string }[] }>("/api/companies");
        setCompanies(
          await Promise.all(
            companies.map(async (c) => ({
              ...c,
              documents: (await get<{ documents: Doc[] }>(`/api/companies/${c.id}/documents`)).documents,
            })),
          ),
        );
      } catch (e) {
        setFailure(failureOf(e));
      }
    })();
  }, []);

  useEffect(() => setPageBox(String(page)), [page]);

  const open = async (d: Doc) => {
    const id = docRequests.start();
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
      setPage(1);
      setClaims(list.claims);
    } catch (e) {
      if (docRequests.isCurrent(id)) setFailure(failureOf(e));
    }
  };

  const pageCount = opened ? opened.pages.length : 0;

  const select = useCallback(
    (index: number) => {
      setSelected(index);
      const c = claims[index];
      if (!c) return;
      if (decide(c, pageCount) !== "do not navigate") setPage(c.page!);
      items.current[index]?.scrollIntoView({ block: "nearest" });
    },
    [claims, pageCount],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (!opened || t.tagName === "INPUT" || e.altKey || e.ctrlKey || e.metaKey) return;
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
  }, [opened, pageCount, selected, claims.length, select]);

  const goTo = () => {
    const n = Number(pageBox);
    if (Number.isInteger(n) && n >= 1 && n <= pageCount) setPage(n);
    else setPageBox(String(page));
  };

  const current = claims[selected];
  const decision = current ? decide(current, pageCount) : null;
  const size = opened?.pages[page - 1];
  const src = opened ? `/api/documents/${opened.id}/pages/${page}.png?scale=${sharp ? "3.0" : "1.5"}` : "";
  const onPage = claims
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => c.page === page && decide(c, pageCount) === "jump and highlight")
    .sort((a, b) => Number(a.i === selected) - Number(b.i === selected)); // the selected box is drawn last, on top

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
      </header>

      <nav aria-label="Companies and documents">
        {health?.data_version === null && <p className="hint">No published data yet. Run: gct publish build</p>}
        {companies.map((c) => (
          <section key={c.id}>
            <h2>{c.name}</h2>
            {c.documents.length === 0 && <p className="hint">No documents.</p>}
            <ul>
              {c.documents.map((d) => (
                <li key={d.id}>
                  <button className="doc" aria-current={opened?.id === d.id} onClick={() => open(d)}>
                    {d.logical_name}
                    {d.version > 1 && <span className="meta"> v{d.version}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>

      <main>
        {failure && <Problem failure={failure} />}
        {!opened && !failure && <p className="hint">Choose a document on the left.</p>}
        {opened && (
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
                  <dt>Source</dt>
                  <dd>
                    <StatusLabel claim={current} />
                  </dd>
                </dl>
                {decision === "do not navigate" && (
                  <p className="hint">
                    {current.page === null
                      ? "This claim is not on a page, so the page was not changed."
                      : `Page ${current.page} is not in this document, so the page was not changed.`}
                  </p>
                )}
              </div>
            )}

            {size && (
              <div className="page" style={{ aspectRatio: `${size.width} / ${size.height}` }}>
                {/* keyed by src: an image of another page or document is never left under these boxes */}
                <img key={src} src={src} alt={`Page ${page} of ${opened.name}`} onLoad={() => setLoadedSrc(src)} />
                {overlayShown(loadedSrc, src) && (
                  <svg viewBox={`${size.left} ${size.top} ${size.width} ${size.height}`} aria-hidden="true">
                    {onPage.flatMap(({ c, i }) =>
                      c.boxes!.map(([x0, top, x1, bottom], k) => (
                        <rect
                          key={`${c.id}-${k}`}
                          className={i === selected ? "box box-selected" : "box"}
                          x={x0}
                          y={top}
                          width={x1 - x0}
                          height={bottom - top}
                          onClick={() => select(i)}
                        />
                      )),
                    )}
                  </svg>
                )}
              </div>
            )}
          </>
        )}
      </main>

      <aside aria-label="Claims">
        <h2>Claims</h2>
        {opened && claims.length === 0 && <p className="hint">No claims for this document. Run: gct extract</p>}
        <ul>
          {claims.map((c, i) => (
            <li key={`${c.id}-${i}`}>
              <button
                ref={(el) => {
                  items.current[i] = el;
                }}
                className="claim"
                aria-pressed={i === selected}
                onClick={() => select(i)}
              >
                <span className="figure">{figure(c)}</span>
                <span className="wording">{c.metric_text ?? "(no wording)"}</span>
                <span className="meta">{c.page === null ? "no page" : `page ${c.page}`}</span>
                <StatusLabel claim={c} />
              </button>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
