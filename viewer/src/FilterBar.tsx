import { useEffect, useRef, useState } from "react";
import { CHOICES, type Filter, isEmpty, type ListField, type SeriesValue, seriesText, toggle, withPeriod, withText } from "./records.ts";

type Company = { id: number; name: string; documents: { id: number; logical_name: string; version: number }[] };

const WORDED: [ListField, string][] = [
  ["metric", "Metric"], ["boundary", "Boundary"], ["claim_state", "Claim state"], ["evidence", "Evidence"],
  ["match", "Matching"], ["comparison", "Comparison"], ["review", "Review"],
];

/** A list field as a disclosure of checkboxes; its summary names how many values are chosen. */
function Choices({ field, label, options, filter, onChange }: {
  field: ListField; label: string; options: [string | number, string][]; filter: Filter; onChange: (f: Filter) => void;
}) {
  const chosen = (filter[field] ?? []) as (string | number)[];
  return (
    <details className="choices" name="filter-choices">
      <summary>
        {label}
        {chosen.length > 0 && <span className="chosen"> {chosen.length}</span>}
      </summary>
      <fieldset>
        <legend className="visually-hidden">{label}</legend>
        {options.length === 0 && <p className="hint">None in this data version.</p>}
        {options.map(([value, words]) => (
          <label key={String(value)}>
            <input type="checkbox" checked={chosen.includes(value)} onChange={() => onChange(toggle(filter, field, value))} />{" "}
            {words}
          </label>
        ))}
      </fieldset>
    </details>
  );
}

/** One control per field of the filter object (F1). Companies and documents are those of the current version; the
 * series those of the pinned version (the values shape, F11 g). */
export function FilterBar({ filter, onChange, companies, series }: {
  filter: Filter; onChange: (f: Filter) => void; companies: Company[]; series: SeriesValue[];
}) {
  const [text, setText] = useState(filter.text ?? "");
  const sent = useRef(filter.text ?? ""); // the wording this bar last put in the filter
  const company = (id: number) => companies.find((c) => c.id === id)?.name ?? `company ${id}`;
  useEffect(() => {
    // A wording set from outside the bar (a saved view, a guided question) shows in the input, as the period
    // inputs do; the bar's own wording coming back leaves what was typed since.
    if ((filter.text ?? "") !== sent.current) setText((sent.current = filter.text ?? ""));
  }, [filter.text]);
  useEffect(() => {
    // Typing waits a moment before the count is asked again; each answer replaces the last (no blocking wait).
    const t = setTimeout(() => {
      if ((filter.text ?? "") !== text) onChange(withText(filter, (sent.current = text)));
    }, 300);
    return () => clearTimeout(t);
  }, [text, filter, onChange]);
  const clear = () => {
    setText("");
    onChange({});
  };
  return (
    <form className="filter-bar" aria-label="Filter" onSubmit={(e) => {
      e.preventDefault();
      onChange(withText(filter, (sent.current = text)));
    }}>
      <Choices field="company" label="Company" options={companies.map((c) => [c.id, c.name])} filter={filter}
        onChange={onChange} />
      <Choices field="document" label="Document" filter={filter} onChange={onChange}
        options={companies.flatMap((c) => c.documents.map((d): [number, string] =>
          [d.id, `${c.name}: ${d.logical_name}${d.version > 1 ? ` v${d.version}` : ""}`]))} />
      {WORDED.map(([field, label]) => (
        <Choices key={field} field={field} label={label} options={CHOICES[field]} filter={filter} onChange={onChange} />
      ))}
      <label>
        Metric wording{" "}
        <input type="search" name="text" maxLength={200} value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <label>
        Period from{" "}
        <input type="date" name="from" value={filter.period?.from ?? ""}
          onChange={(e) => onChange(withPeriod(filter, "from", e.target.value))} />
      </label>
      <label>
        to{" "}
        <input type="date" name="to" value={filter.period?.to ?? ""}
          onChange={(e) => onChange(withPeriod(filter, "to", e.target.value))} />
      </label>
      <Choices field="series" label="Series" filter={filter} onChange={onChange}
        options={series.map((s): [string, string] => [s.id, seriesText(s, company(s.company_id))])} />
      {!isEmpty(filter) && <button type="button" onClick={clear}>Clear the filter</button>}
    </form>
  );
}
