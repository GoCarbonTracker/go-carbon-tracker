// Drives the viewer in a headless Chrome over the DevTools protocol (Node's global WebSocket, no packages).
// usage: node viewer_browser.mjs <chrome debugging port> <viewer url> [stale|shell|filterbar]; prints one JSON object.
const [port, url, mode] = process.argv.slice(2);

const target = await (await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, { method: "PUT" })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok) => (ws.onopen = ok));
let next = 0;
const waiting = new Map();
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && waiting.has(d.id)) waiting.get(d.id)(d);
};
const send = (method, params) =>
  new Promise((ok) => {
    waiting.set(++next, ok);
    ws.send(JSON.stringify({ id: next, method, params }));
  });

const page = async () => {
  const wait = async (fn, what) => {
    for (let i = 0; i < 100; i++) {
      const v = fn();
      if (v) return v;
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error(`timed out waiting for ${what}`);
  };
  const claim = (text) => [...document.querySelectorAll("button.claim")].find((b) => b.textContent.includes(text));
  const panel = () => document.querySelector(".selected")?.innerText ?? "";
  const set = (name, value) => {
    const el = document.querySelector(`form.correct input[name=${name}]`);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  };
  (await wait(() => document.querySelector("button.doc"), "the document list")).click();
  (await wait(() => claim("9,877"), "the claims")).click();
  await wait(() => document.querySelector("form.correct"), "the form on a current claim");
  const before = panel();
  set("value", "9,878");
  set("contributor", "ann");
  set("capacity", "analyst");
  set("rationale", "second look");
  await wait(() => !document.querySelector("form.correct button").disabled, "an enabled submit");
  document.querySelector("form.correct button").click();
  await wait(() => panel().includes("9,878") && panel().includes("replaced 9,877"), "the corrected panel");
  const after = panel();
  claim("not found in the newest reading").click();
  await wait(() => panel().includes("not found in the newest reading"), "a claim that is not current");
  return { before, after, notCurrentPanel: panel(), notCurrentHasForm: !!document.querySelector("form.correct") };
};

// Story 5.4 F1: a company confirmation is filled in on the newest version, another writer's correction publishes
// meanwhile, then the stale form is submitted: the refusal must stay on screen after the panel reloads.
const fill = async () => {
  const wait = async (fn, what) => {
    for (let i = 0; i < 100; i++) {
      const v = fn();
      if (v) return v;
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error(`timed out waiting for ${what}`);
  };
  const byText = (sel, text) => [...document.querySelectorAll(sel)].find((b) => b.textContent.includes(text));
  (await wait(() => document.querySelector("button.doc"), "the document list")).click();
  (await wait(() => byText("button.claim", "9,877"), "the claims")).click();
  (await wait(() => byText("button.link", "Add a company confirmation"), "the reviews section")).click();
  const f = await wait(() => document.querySelector("form.record"), "the form");
  const set = (name, value) => {
    const el = f.querySelector(`input[name=${name}]`);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  };
  set("contributor", "ann");
  set("capacity", "analyst");
  f.querySelector("input[value=accepted]").click();
  set("scope", "Scope 1");
  set("conclusion", "stale entry");
  await wait(() => !f.querySelector("button[type=submit]").disabled, "an enabled submit");
  return true;
};

const submit = async () => {
  const wait = async (fn, what) => {
    for (let i = 0; i < 100; i++) {
      const v = fn();
      if (v) return v;
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error(`timed out waiting for ${what}`);
  };
  const version = () => document.querySelector("header")?.innerText ?? ""; // "published data version N"
  const before = version();
  document.querySelector("form.record button[type=submit]").click();
  await wait(() => version() !== before, "the panel to reload on the new published version");
  await new Promise((r) => setTimeout(r, 500)); // let the remounted panel settle
  return {
    header: version(),
    problem: document.querySelector(".reviews .problem")?.innerText ?? null,
    panel: document.querySelector(".selected")?.innerText ?? "",
  };
};

// Story 6.1 H on tests/gate_fixture.py: the Tables and Graphs section filters and counts on its pinned version; after
// another writer publishes, the next request is refused (409) and the notice offers the new version.
const shellFilter = async () => {
  const wait = async (fn, what) => {
    for (let i = 0; i < 100; i++) {
      const v = fn();
      if (v) return v;
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error(`timed out waiting for ${what}`);
  };
  const line = () => document.querySelector(".count-line")?.innerText ?? "";
  const tick = (field, words) =>
    [...[...document.querySelectorAll(".choices")].find((d) => d.querySelector("summary").innerText.startsWith(field))
      .querySelectorAll("label")].find((l) => l.textContent.trim() === words).querySelector("input").click();
  (await wait(() => [...document.querySelectorAll(".sections button")].find((b) => b.textContent === "Tables and Graphs"),
    "the section switch")).click();
  const choices = (field) =>
    [...document.querySelectorAll(".choices")].find((d) => d.querySelector("summary").innerText.startsWith(field));
  await wait(() => choices("Company")?.querySelector("label"), "the companies in the filter bar");
  const all = await wait(() => line(), "the count of every claim");
  tick("Company", "Acme");
  const acme = await wait(() => line() !== all && line(), "the count of Acme's claims");
  // Review F4: opening a second choice panel closes the first, so at most one lies over the count line
  choices("Company").querySelector("summary").click();
  choices("Evidence").querySelector("summary").click();
  const openPanels = document.querySelectorAll(".choices[open]").length;
  choices("Evidence").querySelector("summary").click();
  return {
    all, acme, openPanels, evidenceHidden: document.querySelector("main").hidden,
    lines: document.querySelector(".count").innerText,
    series: [...document.querySelectorAll(".choices")].find((d) => d.querySelector("summary").textContent
      .startsWith("Series")).querySelectorAll("label").length,
  };
};

const shellStale = async () => {
  const wait = async (fn, what) => {
    for (let i = 0; i < 100; i++) {
      const v = fn();
      if (v) return v;
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error(`timed out waiting for ${what}: ${document.querySelector(".records").innerText}`);
  };
  const tick = (field, words) =>
    [...[...document.querySelectorAll(".choices")].find((d) => d.querySelector("summary").innerText.startsWith(field))
      .querySelectorAll("label")].find((l) => l.textContent.trim() === words).querySelector("input").click();
  tick("Company", "Beta");
  const notice = (await wait(() => document.querySelector(".notice"), "the newer-version notice")).innerText;
  document.querySelector(".notice button").click();
  const reloaded = await wait(() => !document.querySelector(".notice") && document.querySelector(".count-line")?.innerText,
    "the count on the new version");
  return { notice, reloaded };
};

// Story 6.2, the Tables tab: page-side helpers kept on window.T, so the steps between real key presses stay short.
const tablesHelpers = () => {
  const wait = async (fn, what) => {
    for (let i = 0; i < 100; i++) {
      const v = fn();
      if (v) return v;
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error(`timed out waiting for ${what}: ${document.querySelector(".tables-paging")?.innerText}, busy `
      + `${table()?.getAttribute("aria-busy")}: ${document.querySelector(".records")?.innerText.slice(0, 400)}`);
  };
  const table = () => document.querySelector("table.claims-table");
  const rows = () => [...document.querySelectorAll("tr.claim-row")];
  const idOf = (tr) => Number(tr.querySelector("input.select-row").getAttribute("aria-label").match(/^Select claim (\d+):/)[1]);
  const T = {
    wait, table, rows, idOf,
    ids: () => rows().map(idOf),
    row: (id) => rows().find((tr) => idOf(tr) === id),
    header: (name) => [...table().querySelectorAll("th")].find((h) => h.textContent.replace(/[▲▼]/g, "").trim() === name),
    sorts: () => [...table().querySelectorAll("th[aria-sort]")].map((h) => `${h.textContent.replace(/[▲▼]/g, "").trim()} ${h.getAttribute("aria-sort")}`),
    paging: () => document.querySelector(".tables-paging span")?.innerText ?? null,
    button: (word) => [...document.querySelectorAll(".tables-paging button")].find((b) => b.textContent === word),
    disabled: () => [...document.querySelectorAll(".tables-paging button")].filter((b) => b.disabled).map((b) => b.textContent),
    caption: () => table()?.querySelector("caption").innerText ?? null,
    count: () => document.querySelector(".selection-count span")?.innerText ?? null,
    checked: () => rows().filter((tr) => tr.querySelector("input.select-row").checked).map(idOf),
    cleared: () => document.querySelector(".tables [role=status]")?.innerText ?? null,
    settled: () => !!table() && table().getAttribute("aria-busy") === "false",
    section: (name) => [...document.querySelectorAll(".sections button")].find((b) => b.textContent === name).click(),
    scroll: () => document.querySelector(".records").scrollTop,
    active: () => {
      const a = document.activeElement;
      if (a?.classList.contains("claim-row")) return `row ${idOf(a)}`;
      return `${a?.tagName} ${(a?.getAttribute("aria-label") ?? a?.textContent ?? "").replace(/[▲▼]/g, "").trim().slice(0, 40)}`;
    },
    wording: (text) => {
      const el = document.querySelector(".filter-bar input[name=text]");
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, text);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    },
    tick: (field, words) => [...[...document.querySelectorAll(".choices")].find((d) => d.querySelector("summary").innerText
      .startsWith(field)).querySelectorAll("label")].find((l) => l.textContent.trim() === words).querySelector("input").click(),
  };
  window.T = T;
  return true;
};

// One step in the page; the helpers are put in again when the page has been (re)loaded since.
const tablesStep = (fn) => run(`() => { if (!window.T) (${tablesHelpers})(); return (${fn})(); }`);
const tablesReady = async () => {
  for (let i = 0; i < 100 && !(await run(() => !!document.querySelector(".sections button"))); i++) {
    await new Promise((ok) => setTimeout(ok, 100)); // the new tab can still be about:blank
  }
};

// A real key press through the DevTools protocol (Tab moves focus only this way).
const KEYS = { Enter: [13, "\r"], " ": [32, " "], Tab: [9, ""], ArrowDown: [40, ""], ArrowUp: [38, ""], Escape: [27, ""] };
const press = async (key) => {
  const [code, text] = KEYS[key];
  const base = { key, code: key === " " ? "Space" : key, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code };
  await send("Input.dispatchKeyEvent", { type: text ? "keyDown" : "rawKeyDown", ...base, ...(text ? { text } : {}) });
  await send("Input.dispatchKeyEvent", { type: "keyUp", ...base });
  await new Promise((ok) => setTimeout(ok, 150));
};

// G2 Tables part on tests/gate_fixture.py: counts and version, the Value sort both ways, the keyboard, a row's page with
// its box, a spreadsheet row's cell view, the Evidence selection left alone, a filter change clearing the checks.
const tablesGate = async () => {
  const out = {};
  const step = tablesStep;
  await tablesReady();
  out.evidenceBefore = await step(async () => {
    (await T.wait(() => [...document.querySelectorAll("button.doc")].find((b) => b.textContent.includes("acme-2025.pdf")),
      "the document list")).click();
    (await T.wait(() => document.querySelectorAll("button.claim")[1], "the claims")).click();
    return (await T.wait(() => document.querySelector("button.claim[aria-pressed=true]"), "the selected claim")).textContent;
  });
  Object.assign(out, await step(async () => {
    T.section("Tables and Graphs");
    await T.wait(() => T.settled(), "the table");
    const own = T.rows().flatMap((tr) => [3, 6, 7, 8, 9, 10].map((i) => tr.cells[i].innerText));
    return {
      countLine: document.querySelector(".count-line").innerText, caption: T.caption(), paging: T.paging(),
      disabled: T.disabled(), ids: T.ids(), sortsBefore: T.sorts(), companies: [...new Set(T.rows().map((tr) => tr.cells[1].innerText))],
      reviewButton: !!T.header("Review").querySelector("button"), selectHeader: T.table().querySelector("input.select-page").getAttribute("aria-label"),
      headers: [...T.table().querySelectorAll("thead th")].map((h) => `${h.getAttribute("scope")} ${h.innerText}`),
      own: [T.caption(), T.paging(), ...[...T.table().querySelectorAll("thead th")].map((h) => h.innerText), ...own].join("\n"),
      tableText: T.table().innerText,
      labels: T.rows().map((tr) => tr.querySelector("input.select-row").getAttribute("aria-label")),
      rowTabStops: T.rows().map((tr) => tr.tabIndex),
      inRowTabStops: T.rows().flatMap((tr) => [...tr.querySelectorAll("input, button")].map((x) => x.tabIndex)),
    };
  }));
  // Enter, then Space on the Value header, then a click: ascending, descending, ascending.
  const sorted = async () => step(async () => {
    await new Promise((r) => setTimeout(r, 200));
    await T.wait(() => T.settled(), "the sorted rows");
    return { sorts: T.sorts(), ids: T.ids() };
  });
  await step(() => T.header("Value").querySelector("button").focus());
  await press("Enter");
  out.valueAsc = await sorted();
  await press(" ");
  out.valueDesc = await sorted();
  await step(() => T.header("Value").querySelector("button").click());
  out.valueAgain = await sorted();
  // Tab from the Tables tab into the table: the header controls, then one row.
  await step(() => document.getElementById("tab-tables").focus());
  out.tabStops = [];
  for (let i = 0; i < 15 && !out.tabStops.at(-1)?.startsWith("row"); i++) {
    await press("Tab");
    out.tabStops.push(await step(() => T.active()));
  }
  await press("ArrowDown");
  out.afterDown = await step(() => T.active());
  out.scrollBefore = await step(() => T.scroll()); // after the focus move, which may scroll the row into view
  await press(" ");
  out.afterSpace = await step(() => ({ count: T.count(), checked: T.checked(), scroll: T.scroll(), active: T.active() }));
  await press("ArrowUp");
  await press("ArrowUp"); // stops at the first row
  out.afterUp = await step(() => T.active());
  out.afterClick = await step(() => {
    const first = T.row(T.checked()[0]);
    const other = T.rows().find((tr) => tr.cells[1].innerText !== first.cells[1].innerText);
    other.querySelector("input.select-row").click();
    return { count: T.count(), checked: T.checked(), companies: T.checked().map((id) => T.row(id).cells[1].innerText) };
  });
  out.evidenceAfterKeys = await step(async () => {
    T.section("Evidence");
    const text = document.querySelector("button.claim[aria-pressed=true]")?.textContent ?? null; // still hidden: no innerText
    T.section("Tables and Graphs");
    return text;
  });
  // Enter on Beta's 2,000 row (page 1, a box): the Evidence section with that claim selected and its box drawn.
  await step(async () => {
    await T.wait(() => T.settled(), "the table again");
    T.row(T.rows().map(T.idOf).find((id) => T.row(id).cells[5].innerText.startsWith("2,000"))).focus();
  });
  out.boxRow = await step(() => T.active());
  await press("Enter");
  out.opened = await step(async () => {
    await T.wait(() => !document.querySelector("main").hidden && document.querySelector("rect.box-selected"), "the page with its box");
    return {
      doc: document.querySelector("button.doc[aria-current=true]").innerText,
      selected: document.querySelector("button.claim[aria-pressed=true]").innerText,
      boxes: document.querySelectorAll("rect.box-selected").length, recordsHidden: document.querySelector(".records").hidden,
    };
  });
  out.back = await step(async () => {
    T.section("Tables and Graphs");
    await T.wait(() => T.settled(), "the table after Evidence");
    return { sorts: T.sorts(), ids: T.ids(), checked: T.checked(), count: T.count() };
  });
  // The spreadsheet row: the cell view, no page read; Escape closes it and focus is back on the row.
  out.cellRow = await step(() => {
    window.before = performance.getEntriesByType("resource").length;
    const tr = T.rows().find((r) => r.cells[3].innerText.startsWith("sheet"));
    tr.focus();
    return T.active();
  });
  await press("Enter");
  out.cell = await step(async () => {
    const v = await T.wait(() => document.querySelector(".cell-view td.marked") && document.querySelector(".cell-view"), "the cell view");
    return {
      heading: v.querySelector("h2").innerText, marked: v.querySelector("td.marked").innerText,
      reads: performance.getEntriesByType("resource").slice(window.before).map((e) => new URL(e.name).pathname),
    };
  });
  await press("Escape");
  out.afterEscape = await step(() => ({ open: !!document.querySelector(".cell-view"), active: T.active() }));
  out.cleared = await step(async () => {
    T.tick("Company", "Acme");
    await T.wait(() => T.cleared() && T.settled() && T.ids().length < 14, "the Acme rows");
    return { cleared: T.cleared(), count: T.count(), sorts: T.sorts(), companies: [...new Set(T.rows().map((tr) => tr.cells[1].innerText))] };
  });
  out.requests = await step(() => performance.getEntriesByType("resource").map((e) => e.name));
  return out;
};

// Paging on a workspace of more than two pages: First, Next, Last and the rows line; checks kept across pages; a late
// page dropped (the test delays offset 200); a filter change while loading; no match; another writer's publish.
const tablesPaging = async () => {
  const out = {};
  const step = tablesStep;
  await tablesReady();
  const shown = () => step(() => ({ paging: T.paging(), disabled: T.disabled(), caption: T.caption(), count: T.count(), checked: T.checked() }));
  const go = (word, rows) => step(`async () => {
    T.button(${JSON.stringify(word)}).click();
    await T.wait(() => T.settled() && T.paging() === ${JSON.stringify(rows)}, ${JSON.stringify(rows)});
  }`);
  await step(async () => {
    T.section("Tables and Graphs");
    await T.wait(() => T.settled(), "the table");
    T.rows()[0].querySelector("input.select-row").click();
  });
  out.first = await shown();
  await go("Next", "Rows 201 to 400 of 420");
  await step(() => T.rows()[5].querySelector("input.select-row").click());
  out.second = await shown();
  await go("Last", "Rows 401 to 420 of 420");
  await step(() => T.rows()[19].querySelector("input.select-row").click());
  out.last = await shown();
  await go("First", "Rows 1 to 200 of 420");
  out.backFirst = await shown();
  // Keyboard paging: Enter on Next twice; at the last page focus moves to Previous.
  await step(() => T.button("Next").focus());
  await press("Enter");
  await step(() => T.wait(() => T.settled() && T.paging() === "Rows 201 to 400 of 420", "page 2"));
  await press("Enter");
  await step(() => T.wait(() => T.settled() && T.paging() === "Rows 401 to 420 of 420", "page 3"));
  out.keyboardEnd = await step(() => ({ active: T.active(), disabled: T.disabled() }));
  await go("First", "Rows 1 to 200 of 420");
  // Next (offset 200, delayed by the test) then Last before it answers: Last stays.
  out.late = await step(async () => {
    T.button("Next").click();
    await new Promise((r) => setTimeout(r, 100));
    T.button("Last").click();
    await T.wait(() => T.settled() && T.paging() === "Rows 401 to 420 of 420", "the last page");
    await new Promise((r) => setTimeout(r, 2500)); // the delayed page 2 answers meanwhile
    return { paging: T.paging(), busy: T.table().getAttribute("aria-busy") };
  });
  // On the last page, Next (delayed) then a filter change: page 1 of the new filter, checks cleared with the line.
  out.filtered = await step(async () => {
    T.button("Previous").click();
    await new Promise((r) => setTimeout(r, 100));
    T.wording("Measure 1");
    await T.wait(() => T.settled() && T.cleared() && T.paging()?.endsWith("of 222"), "the filtered rows");
    await new Promise((r) => setTimeout(r, 2500));
    return { paging: T.paging(), cleared: T.cleared(), count: T.count(), checked: T.checked() };
  });
  out.nothing = await step(async () => {
    T.wording("no such wording");
    await T.wait(() => !T.table() && document.querySelector(".count")?.innerText.includes("No claims match"), "no match");
    return { table: !!T.table(), paging: !!document.querySelector(".tables-paging"), count: document.querySelector(".count").innerText };
  });
  await step(async () => {
    T.wording("");
    await T.wait(() => T.settled() && T.paging() === "Rows 1 to 200 of 420", "every row again");
    T.rows()[2].querySelector("input.select-row").click();
  });
  out.beforeWriter = await shown();
  return out;
};

const tablesStale = async () => {
  const step = tablesStep;
  const out = {};
  out.notice = await step(async () => {
    T.button("Next").click();
    return (await T.wait(() => document.querySelector(".notice"), "the newer-version notice")).innerText;
  });
  out.stale = await step(async () => {
    await T.wait(() => T.settled(), "the table to settle");
    return { paging: T.paging(), caption: T.caption(), checked: T.checked(), alert: document.querySelector(".tables [role=alert]")?.innerText ?? null };
  });
  out.reloaded = await step(async () => {
    document.querySelector(".notice button").click();
    await T.wait(() => T.settled() && T.caption()?.endsWith("version 2") && T.cleared() && document.querySelector(".count-line"),
      "the table on version 2");
    return { paging: T.paging(), caption: T.caption(), cleared: T.cleared(), count: T.count(), countLine: document.querySelector(".count-line")?.innerText };
  });
  return out;
};

// The viewer fixture's page-999 claim: Enter opens nothing and says so; the page count is read, no page is.
const tablesNoLocation = async () => {
  await tablesReady();
  await tablesStep(async () => {
    T.section("Tables and Graphs");
    await T.wait(() => T.settled(), "the table");
    T.rows().find((tr) => tr.cells[3].innerText === "page 999").focus();
  });
  await press("Enter");
  const out = await tablesStep(async () => {
    const said = await T.wait(() => document.querySelector(".tables-said").innerText, "the no-location line");
    return {
      said, evidenceHidden: document.querySelector("main").hidden, cell: !!document.querySelector(".cell-view"),
      reads: performance.getEntriesByType("resource").map((e) => new URL(e.name).pathname).filter((p) => p.startsWith("/api/documents")),
    };
  });
  // The document is gone by the next read (the test answers 404): its cause in the Tables alert line, nothing opened.
  await tablesStep(() => T.rows().find((tr) => tr.cells[3].innerText === "page 1").focus());
  await press("Enter");
  out.gone = await tablesStep(async () => ({
    alert: (await T.wait(() => document.querySelector(".tables [role=alert]"), "the alert line")).innerText,
    evidenceHidden: document.querySelector("main").hidden, rows: T.rows().length, active: T.active().startsWith("row"),
  }));
  return out;
};

const run = async (fn) => {
  let r;
  for (let i = 0; i < 50; i++) {
    r = await send("Runtime.evaluate", { expression: `(${fn})()`, awaitPromise: true, returnByValue: true });
    if (r.result) break; // an error here: the new tab has no page to run in yet
    await new Promise((ok) => setTimeout(ok, 100));
  }
  if (!r.result || r.result.exceptionDetails) {
    console.error(JSON.stringify(r));
    process.exit(1);
  }
  return r.result.result.value;
};

let out;
if (mode === "stale") {
  await run(fill);
  // The second writer: a correction through the API with the session key, which publishes a new version.
  const origin = new URL(url).origin;
  const auth = { Authorization: `Bearer ${new URL(url).searchParams.get("token")}` };
  const { claims } = await (await fetch(`${origin}/api/documents/1/claims`, { headers: auth })).json();
  const id = claims.find((c) => c.value_text === "9,877").id;
  const w = await fetch(`${origin}/api/claims/${id}/corrections`, {
    method: "POST",
    headers: { ...auth, "Content-Type": "application/json" },
    body: JSON.stringify({ value: "9,879", contributor: "ann", capacity: "analyst", rationale: "other tab" }),
  });
  out = { second_writer: w.status, ...(await run(submit)) };
} else if (mode === "shell") {
  const first = await run(shellFilter);
  const origin = new URL(url).origin;
  const auth = { Authorization: `Bearer ${new URL(url).searchParams.get("token")}` };
  const { claims } = await (await fetch(`${origin}/api/documents/1/claims`, { headers: auth })).json();
  const w = await fetch(`${origin}/api/claims/${claims[0].id}/corrections`, {
    method: "POST",
    headers: { ...auth, "Content-Type": "application/json" },
    body: JSON.stringify({ value: "1,235", contributor: "ana", capacity: "analyst", rationale: "other tab" }),
  });
  out = { ...first, second_writer: w.status, ...(await run(shellStale)) };
} else if (mode === "tables") {
  if (process.argv[5] === "paging") {
    out = await tablesPaging();
    const origin = new URL(url).origin;
    const auth = { Authorization: `Bearer ${new URL(url).searchParams.get("token")}` };
    const { claims } = await (await fetch(`${origin}/api/documents/1/claims`, { headers: auth })).json();
    const w = await fetch(`${origin}/api/claims/${claims[0].id}/corrections`, {
      method: "POST",
      headers: { ...auth, "Content-Type": "application/json" },
      body: JSON.stringify({ value: "2", contributor: "ana", capacity: "analyst", rationale: "other tab" }),
    });
    out = { ...out, second_writer: w.status, ...(await tablesStale()) };
  } else if (process.argv[5] === "nolocation") out = await tablesNoLocation();
  else out = await tablesGate();
} else if (mode === "filterbar") {
  out = await run(async () => {
    for (let i = 0; i < 50 && !window.out; i++) await new Promise((r) => setTimeout(r, 100));
    return window.out;
  });
} else {
  out = await run(page);
}
ws.close();
console.log(JSON.stringify(out));
