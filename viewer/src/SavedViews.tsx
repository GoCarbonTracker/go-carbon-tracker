import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import type { Filter } from "./records.ts";
import { exists, existsText, KEPT_FILTER, NO_VIEWS, ready, removedLine, savedLine, savedText, type Tab } from "./transfer.ts";
import "./savedviews.css";

type Failure = { cause: string; next_action: string };
export type SavedView = { name: string; filter: Filter; section: Tab; contributor: string; saved_at: string; earlier: number };

async function call<T>(path: string, body?: object): Promise<T> {
  const r = await fetch(path, body === undefined ? { headers: { Accept: "application/json" } } : {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw data as Failure;
  return data as T;
}

const failureOf = (e: unknown): Failure =>
  typeof e === "object" && e !== null && "cause" in e ? (e as Failure) : { cause: String(e), next_action: "Reload the page." };

function Problem({ failure }: { failure: Failure }) {
  return <p className="problem" role="alert">{failure.cause} {failure.next_action}</p>;
}

/** Escape closes the innermost open form or panel without saving; the panel's own Escape is not reached. */
const escape = (close: () => void) => (e: KeyboardEvent) => {
  if (e.key !== "Escape") return;
  e.preventDefault();
  e.stopPropagation();
  close();
};

/** One saved view in the list, with Open and Remove; Remove asks for the contributor key and a confirmation. */
function Item({ view, who, setWho, onOpen, onRemoved }: {
  view: SavedView; who: string; setWho: (k: string) => void; onOpen: (v: SavedView) => void;
  onRemoved: (name: string) => Promise<void>;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const removeButton = useRef<HTMLButtonElement>(null);
  const keyBox = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (asking) keyBox.current?.focus();
  }, [asking]);
  const cancel = () => {
    setAsking(false);
    setFailure(null);
    setTimeout(() => removeButton.current?.focus()); // after the form is gone
  };
  const remove = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      await call("/api/views/remove", { name: view.name, contributor: who.trim() });
      await onRemoved(view.name);
    } catch (err) {
      setFailure(failureOf(err));
      setBusy(false);
    }
  };
  return (
    <li className="saved-view">
      <div className="saved-view-head">
        <span className="saved-view-name">{view.name}</span>
        <span className="meta">{savedText(view)}</span>
        <span className="saved-view-actions">
          <button type="button" onClick={() => onOpen(view)}>Open</button>
          <button type="button" ref={removeButton} aria-expanded={asking} onClick={() => (asking ? cancel() : setAsking(true))}>
            Remove
          </button>
        </span>
      </div>
      {asking && (
        <form className="saved-view-form" aria-label={`Remove ${view.name}`} onSubmit={remove} onKeyDown={escape(cancel)}>
          <label>
            Contributor key{" "}
            <input ref={keyBox} name="contributor" value={who} autoComplete="off" onChange={(e) => setWho(e.target.value)} />
          </label>
          <button type="submit" disabled={busy || !who.trim()}>Remove {view.name}</button>
          <button type="button" onClick={cancel}>Cancel</button>
          {failure && <Problem failure={failure} />}
        </form>
      )}
    </li>
  );
}

/** The Saved views panel (story 6.4 B2): the views of GET /api/views; Save keeps the filter bar's filter and the current
 * tab under a name; Open hands a view to the shell; Remove adds a removal record. Escape or Close shuts the panel and
 * focus goes back to the button that opened it. */
export function SavedViews({ filter, tab, chipShown, onOpen, onClose }: {
  filter: Filter; tab: Tab; chipShown: boolean; onOpen: (v: SavedView) => void; onClose: () => void;
}) {
  const [views, setViews] = useState<SavedView[] | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [name, setName] = useState("");
  const [who, setWho] = useState("");
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<Failure | null>(null);
  const [done, setDone] = useState("");
  const panel = useRef<HTMLElement>(null);
  const opener = useRef(document.activeElement as HTMLElement | null);

  const load = useCallback(async () => {
    setViews((await call<{ views: SavedView[] }>("/api/views")).views);
  }, []);
  useEffect(() => {
    load().catch((e) => setFailure(failureOf(e)));
  }, [load]);

  useEffect(() => {
    panel.current?.focus();
    const back = opener.current;
    return () => back?.focus();
  }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setRefused(null);
    setDone("");
    try {
      const r = await call<{ view: SavedView }>("/api/views", { name, filter, section: tab, contributor: who.trim() });
      setName("");
      setDone(savedLine(r.view.name));
      await load();
    } catch (err) {
      setRefused(failureOf(err));
    } finally {
      setBusy(false);
    }
  };

  const removed = async (gone: string) => {
    setDone(removedLine(gone));
    await load().catch((e) => setFailure(failureOf(e)));
    setTimeout(() => panel.current?.focus()); // the row and its buttons are gone
  };

  const names = views?.map((v) => v.name) ?? [];
  return (
    <section className="views-panel" id="panel-views" aria-labelledby="panel-views-title" tabIndex={-1} ref={panel}
      onKeyDown={escape(onClose)}>
      <div className="views-panel-head">
        <h2 id="panel-views-title">Saved views</h2>
        <button type="button" onClick={onClose}>Close</button>
      </div>
      {failure && <Problem failure={failure} />}
      {!views && !failure && <p className="hint">Reading the saved views.</p>}
      {views?.length === 0 && <p className="hint">{NO_VIEWS}</p>}
      {views && views.length > 0 && (
        <ul className="saved-list">
          {views.map((v) => <Item key={v.name} view={v} who={who} setWho={setWho} onOpen={onOpen} onRemoved={removed} />)}
        </ul>
      )}
      <form className="saved-view-form save" aria-labelledby="save-view-title" onSubmit={save}>
        <h3 id="save-view-title">Save the current filter</h3>
        <label>
          Name{" "}
          <input name="name" value={name} maxLength={80} autoComplete="off" onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Contributor key{" "}
          <input name="contributor" value={who} autoComplete="off" onChange={(e) => setWho(e.target.value)} />
        </label>
        <button type="submit" disabled={busy || !ready(name, who)}>Save</button>
        {exists(name, names) && <p className="meta saved-note">{existsText(name)}</p>}
        {chipShown && <p className="meta saved-note">{KEPT_FILTER}</p>}
        {refused && <Problem failure={refused} />}
      </form>
      <p className="saved-done" aria-live="polite">{done}</p>
    </section>
  );
}
