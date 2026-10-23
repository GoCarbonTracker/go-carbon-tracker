import { useEffect, useRef, useState } from "react";
import { isStale } from "./records.ts";
import { type Chip, choiceChip, choiceText, NO_CHOICES, type Question, questionCount, SERIES_QUESTION, type Tab } from "./transfer.ts";
import "./questions.css";

type Failure = { cause: string; next_action: string };
export type Chosen = { filter: Question["filter"]; section: Tab; chip?: Chip };

/** The guided questions panel (story 6.4 B3): the six questions of GET /api/questions with their counts on the pinned
 * version. A question sets the filter bar and opens its tab; metric-over-time first lists its series, and a series
 * opens Graphs in the series shape. Escape or Close shuts the panel and focus goes back to the button that opened it. */
export function Questions({ pinned, onChoose, onStale, onClose }: {
  pinned: number; onChoose: (c: Chosen) => void; onStale: () => void; onClose: () => void;
}) {
  const [answer, setAnswer] = useState<{ data_version: number; questions: Question[] } | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [open, setOpen] = useState(false); // the series of metric-over-time
  const panel = useRef<HTMLElement>(null);
  const opener = useRef(document.activeElement as HTMLElement | null);

  useEffect(() => {
    let live = true;
    setAnswer(null);
    setFailure(null);
    (async () => {
      const r = await fetch(`/api/questions?data_version=${pinned}`, { headers: { Accept: "application/json" } });
      const data = await r.json();
      if (!live) return;
      if (r.ok) return setAnswer(data);
      setFailure(data);
      if (isStale(r.status, data.cause)) onStale(); // the shell's notice offers the current version
    })().catch((e) => live && setFailure({ cause: String(e), next_action: "Reload the page." }));
    return () => {
      live = false;
    };
  }, [pinned]);

  useEffect(() => {
    panel.current?.focus();
    const back = opener.current;
    return () => back?.focus();
  }, []);

  return (
    <section className="questions-panel" id="panel-questions" aria-labelledby="panel-questions-title" tabIndex={-1}
      ref={panel} onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onClose();
        }
      }}>
      <div className="questions-panel-head">
        <h2 id="panel-questions-title">Questions</h2>
        <button type="button" onClick={onClose}>Close</button>
      </div>
      {failure && <p className="problem" role="alert">{failure.cause} {failure.next_action}</p>}
      {/* The panel's polite region: the counting line, then the questions with their counts, are read out (review L5) */}
      <div aria-live="polite">
        {!answer && !failure && <p className="hint">Counting the questions in data version {pinned}.</p>}
        {answer && (
          <ul className="question-list">
            {answer.questions.map((q) => {
              const series = q.key === SERIES_QUESTION;
              return (
                <li key={q.key}>
                  <button type="button" className="question" aria-expanded={series ? open : undefined}
                    aria-controls={series ? "question-series" : undefined}
                    onClick={() => (series ? setOpen(!open) : onChoose({ filter: q.filter, section: q.section }))}>
                    {q.text}
                  </button>
                  <span className="question-count">{questionCount(q, answer.data_version)}</span>
                  {series && open && (
                    <div id="question-series" aria-live="off">
                      {q.choices.length === 0 ? <p className="hint">{NO_CHOICES}</p> : (
                        <ul className="question-choices" aria-label="Series with two or more periods">
                          {q.choices.map((c) => (
                            <li key={c.series}>
                              <button type="button" className="link" onClick={() =>
                                onChoose({ filter: c.filter, section: "graphs", chip: choiceChip(c, answer.data_version) })}>
                                {choiceText(c)}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
