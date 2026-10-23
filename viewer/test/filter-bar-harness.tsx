// Story 6.1 review F1: the filter bar under a parent that sets a filter with a wording from outside the bar, as a saved
// view or a guided question will. tests/test_viewer.py bundles this file and reads window.out in headless Chrome.
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { FilterBar } from "../src/FilterBar.tsx";
import type { Filter } from "../src/records.ts";

const log: string[] = [];

function Parent() {
  const [filter, setFilter] = useState<Filter>({});
  useEffect(() => void log.push(JSON.stringify(filter)), [filter]);
  useEffect(() => void setTimeout(() => setFilter({ text: "scope 1", company: [1] }), 100), []);
  return <FilterBar filter={filter} onChange={setFilter} companies={[]} series={[]} />;
}

createRoot(document.getElementById("root")!).render(<Parent />);
// Well after the bar's 300 ms debounce
setTimeout(() => {
  (window as unknown as { out: object }).out = {
    log, input: document.querySelector<HTMLInputElement>("input[name=text]")!.value,
  };
}, 1000);
