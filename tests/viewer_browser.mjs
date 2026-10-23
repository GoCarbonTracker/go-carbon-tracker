// Drives the viewer in a headless Chrome over the DevTools protocol (Node's global WebSocket, no packages).
// usage: node viewer_browser.mjs <chrome debugging port> <viewer url> [stale|shell|filterbar|tables|graphs*|transfer|views]
// [sub-mode]; prints one JSON object.
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

// Story 6.4 part B: the transfer bar, the chip and the panels; page helpers on window.P beside window.T.
const partBHelpers = () => {
  const by = (sel, text) => [...document.querySelectorAll(sel)].find((b) => b.textContent.trim() === text);
  const P = {
    by,
    tab: () => document.querySelector(".tabs [aria-selected=true]")?.textContent ?? null,
    bar: () => ({ buttons: [...document.querySelectorAll(".transfer button")].map((b) => `${b.textContent}${b.disabled ? " (disabled)" : ""}`),
      reason: document.querySelector(".transfer-reason")?.textContent ?? "" }),
    press: (i) => document.querySelectorAll(".transfer button")[i].click(),
    chip: () => {
      const c = document.querySelector(".count .chip");
      return c ? { text: c.querySelector("span").textContent, label: c.querySelector("button").getAttribute("aria-label") } : null;
    },
    line: () => document.querySelector(".count-line")?.innerText ?? "",
    cy: () => document.querySelector(".graphs .canvas")?._cyreg?.cy,
    claimNodes: () => P.cy()?.nodes(".claim, .point").map((n) => n.id()).sort() ?? [],
    graph: () => document.querySelector(".graph-count")?.innerText ?? "",
    pick: (ids) => {
      const c = P.cy();
      c.$(":selected").unselect();
      ids.forEach((id) => c.getElementById(id).select());
    },
    set: (el, value) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    },
    active: () => {
      const a = document.activeElement;
      return `${a?.tagName} ${(a?.getAttribute("aria-label") ?? a?.textContent ?? "").trim().slice(0, 60)}`;
    },
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  };
  window.P = P;
  return true;
};
const partBStep = (fn) => run(`() => { if (!window.T) (${tablesHelpers})(); if (!window.P) (${partBHelpers})(); return (${fn})(); }`);

// B1 and G3 on tests/gate_fixture.py: rows to Graphs and back with the same ids, filter and version; the chip; every D10
// reason with no tab change; a series both ways. The other-version reason comes last (the dispatch adds a writer).
const transferGate = async () => {
  const out = {};
  const step = partBStep;
  await tablesReady();
  out.empty = await step(async () => {
    T.section("Tables and Graphs");
    await T.wait(() => T.settled() && P.bar().buttons.length, "the table and its bar");
    const bar = P.bar();
    P.press(0); // disabled: no tab change
    await P.sleep(200);
    return { ...bar, tab: P.tab() };
  });
  out.toGraphs = await step(async () => {
    const rows = [T.rows().find((tr) => tr.cells[5].innerText.startsWith("2,000")), T.rows().find((tr) => tr.cells[3].innerText.startsWith("sheet"))];
    rows.forEach((tr) => tr.querySelector("input.select-row").click());
    await T.wait(() => P.bar().buttons[0] === "Show 2 rows in Graphs", "the enabled bar");
    const bar = P.bar();
    P.press(0);
    await T.wait(() => P.tab() === "Graphs" && P.claimNodes().length === 2 && P.graph(), "the two claims drawn");
    return { picked: rows.map(T.idOf).sort((a, b) => a - b), companies: rows.map((tr) => tr.cells[1].innerText), bar,
      chip: P.chip(), line: P.line(), graph: P.graph(), nodes: P.claimNodes(), cells: P.cy().nodes(".cell").length };
  });
  out.back = await step(async () => {
    P.pick(P.claimNodes());
    await T.wait(() => P.bar().buttons[0] === "Show 2 claims in Tables", "the Graphs bar");
    const bar = P.bar();
    P.press(0);
    await T.wait(() => P.tab() === "Tables" && T.settled() && T.ids().length === 2, "the two rows");
    return { bar, chip: P.chip(), line: P.line(), ids: T.ids().sort((a, b) => a - b), caption: T.caption() };
  });
  // The chip's button by keyboard: the whole filter again, focus on the tab.
  await step(() => document.querySelector(".count .chip button").focus());
  await press("Enter");
  out.removed = await step(async () => {
    await T.wait(() => !P.chip() && T.settled() && T.ids().length === 14, "every row again");
    const active = P.active();
    P.by(".tabs button", "Graphs").click();
    await T.wait(() => P.chip(), "the Graphs chip");
    const graphsChip = P.chip();
    document.querySelector(".count .chip button").click();
    await T.wait(() => !P.chip() && P.claimNodes().length === 14, "the whole graph");
    P.by(".tabs button", "Tables").click();
    return { active, graphsChip, line: P.line() };
  });
  const seriesAsk = async (pick) => {
    await T.wait(() => T.settled() && T.ids().length === 14 && T.checked().length === 0, "the rows, none checked");
    pick().forEach((tr) => tr.querySelector("input.select-row").click());
    await T.wait(() => P.bar().buttons[1] === "Show as a time series", "the time-series button");
    P.press(1);
    await T.wait(() => P.bar().reason || P.tab() === "Graphs", "the answer");
    const r = { reason: P.bar().reason, tab: P.tab() };
    document.querySelector(".selection-count button")?.click(); // Clear selection
    return r;
  };
  const acme = (words) => () => T.rows().filter((tr) => tr.cells[1].innerText === "Acme" && tr.cells[4].innerText.includes(words));
  out.twoSeries = await step(`async () => (${seriesAsk})(() => [(${acme})("Scope 1")()[0], (${acme})("energy")()[0]])`);
  out.noSeries = await step(`async () => (${seriesAsk})(() => T.rows().filter((tr) => tr.cells[4].innerText.includes("Employees")))`);
  out.series = await step(async () => {
    await T.wait(() => T.settled() && T.checked().length === 0, "no rows checked");
    const rows = T.rows().filter((tr) => tr.cells[1].innerText === "Acme" && tr.cells[4].innerText.includes("Scope 1"));
    rows.forEach((tr) => tr.querySelector("input.select-row").click());
    await T.wait(() => P.bar().buttons[1] === "Show as a time series" && !P.bar().buttons[1].includes("disabled"), "the button");
    P.press(1);
    await T.wait(() => P.tab() === "Graphs" && P.claimNodes().length === rows.length && P.claimNodes()[0].startsWith("point:"), "the series drawn");
    return { ids: rows.map(T.idOf).sort((a, b) => a - b), chip: P.chip(), nodes: P.claimNodes(),
      view: document.querySelector(".graph-views [aria-pressed=true]").textContent };
  });
  out.seriesBack = await step(async () => {
    document.querySelector(".count .chip button").click();
    await T.wait(() => P.claimNodes().length === 14, "the whole graph");
    const node = P.cy().nodes(".series")[0];
    P.pick([node.id()]);
    await T.wait(() => P.bar().buttons[1] === "Show this series in Tables", "the series button");
    const bar = P.bar();
    P.press(1);
    await T.wait(() => P.tab() === "Tables" && P.chip() && T.settled() && T.ids().length < 14, "the series rows");
    return { node: node.id(), bar, chip: P.chip(), ids: T.ids().sort((a, b) => a - b) };
  });
  out.kinds = await step(async () => {
    document.querySelector(".count .chip button").click();
    P.by(".tabs button", "Graphs").click();
    await T.wait(() => P.claimNodes().length === 14, "the whole graph");
    const c = P.cy();
    const firsts = new Map();
    c.nodes().forEach((n) => {
      const k = n.classes()[0];
      if (!["claim", "series"].includes(k) && !firsts.has(k)) firsts.set(k, n.id());
    });
    firsts.set("edge", c.edges()[0].id());
    const seen = [];
    for (const [kind, id] of firsts) {
      P.pick([id]);
      await T.wait(() => P.bar().reason.includes("has no rows"), `the reason for ${kind}`);
      P.press(0);
      P.press(1);
      await P.sleep(100);
      seen.push({ kind, id, reason: P.bar().reason, buttons: P.bar().buttons, tab: P.tab() });
    }
    c.$(":selected").unselect();
    P.by(".tabs button", "Tables").click();
    return seen;
  });
  // A series node with a claim node, and two series nodes: one series or claims only.
  out.mixed = await step(async () => {
    P.by(".tabs button", "Graphs").click();
    await T.wait(() => P.claimNodes().length === 14, "the whole graph");
    const c = P.cy();
    const [one, two] = c.nodes(".series").map((n) => n.id());
    const seen = [];
    for (const ids of [[one, c.nodes(".claim")[0].id()], [one, two]]) {
      P.pick(ids);
      await T.wait(() => P.bar().reason.startsWith("Select one series"), `the reason for ${ids}`);
      P.press(0);
      P.press(1);
      await P.sleep(100);
      seen.push({ ids, reason: P.bar().reason, buttons: P.bar().buttons, tab: P.tab() });
    }
    c.$(":selected").unselect();
    P.by(".tabs button", "Tables").click();
    return seen;
  });
  return out;
};

// After a second writer publishes: the selection is of a version no longer current; Reload clears it (6.2 T6).
const transferStale = async () => {
  const step = partBStep;
  return step(async () => {
    await T.wait(() => T.settled() && T.checked().length === 0, "no rows checked");
    T.rows()[0].querySelector("input.select-row").click();
    await T.wait(() => !P.bar().buttons[0].includes("disabled"), "an enabled button");
    P.press(0);
    await T.wait(() => P.bar().reason.startsWith("Data version"), "the version reason");
    const stale = { ...P.bar(), tab: P.tab(), notice: document.querySelector(".notice")?.innerText ?? null };
    document.querySelector(".notice button").click();
    await T.wait(() => P.line().includes("version 2") && T.settled() && T.checked().length === 0, "version 2");
    return { stale, reloaded: { ...P.bar(), tab: P.tab(), line: P.line() } };
  });
};

// The 501-claim fixture of tests/test_viewer_graphs.py: a selection across three Tables pages is drawn whole, and one of
// more than 500 rows shows the limit, no tab change.
const transferLimit = async () => {
  const step = partBStep;
  await tablesReady();
  const across = await step(async () => {
    T.section("Tables and Graphs");
    await T.wait(() => T.settled() && T.paging() === "Rows 1 to 200 of 501", "page 1");
    for (const paging of ["Rows 201 to 400 of 501", "Rows 401 to 501 of 501"]) {
      T.table().querySelector("input.select-page").click();
      T.button("Next").click();
      await T.wait(() => T.settled() && T.paging() === paging, paging);
    }
    T.rows().slice(0, 5).forEach((tr) => tr.querySelector("input.select-row").click());
    await T.wait(() => T.count() === "405 selected" && P.bar().buttons[0] === "Show 405 rows in Graphs", "405 selected");
    const bar = P.bar();
    P.press(0);
    await T.wait(() => P.tab() === "Graphs" && P.claimNodes().length === 405, "405 claims drawn");
    return { bar, chip: P.chip(), nodes: P.claimNodes().length, graph: P.graph() };
  });
  const over = await step(async () => {
    P.by(".tabs button", "Tables").click();
    await T.wait(() => T.settled() && T.paging() === "Rows 401 to 501 of 501", "page 3 again");
    T.table().querySelector("input.select-page").click();
    await T.wait(() => T.count() === "501 selected" && P.bar().reason, "501 selected");
    P.press(0);
    await P.sleep(200);
    return { ...P.bar(), tab: P.tab() };
  });
  return { across, over };
};

// Story 6.4 part B, the `views` mode on tests/gate_fixture.py: the Saved views and Questions panels. Page helpers on
// window.V (with window.T); one sub-mode per page visit, the gct writes between visits done by the test.
const viewsHelpers = () => {
  const V = {
    by: (sel, text) => [...document.querySelectorAll(sel)].find((b) => b.textContent.trim() === text),
    tab: () => document.querySelector(".tabs [aria-selected=true]")?.textContent ?? null,
    line: () => document.querySelector(".count-line")?.innerText ?? "",
    count: () => document.querySelector(".count")?.innerText ?? "",
    chip: () => document.querySelector(".count .chip span")?.textContent ?? null,
    views: () => document.querySelector(".views-panel"),
    questions: () => document.querySelector(".questions-panel"),
    items: () => [...document.querySelectorAll(".saved-view")].map((li) => ({
      name: li.querySelector(".saved-view-name").textContent, meta: li.querySelector(".meta").textContent })),
    item: (name) => [...document.querySelectorAll(".saved-view")].find((li) => li.querySelector(".saved-view-name").textContent === name),
    set: (el, value) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    },
    chosen: (field) => [...document.querySelectorAll(".choices")].find((d) => d.querySelector("summary").innerText.startsWith(field))
      .querySelector(".chosen")?.textContent.trim() ?? "",
    cy: () => document.querySelector(".graphs .canvas")?._cyreg?.cy,
    active: () => {
      const a = document.activeElement;
      return `${a?.tagName} ${(a?.getAttribute("aria-label") ?? (a?.tagName === "SECTION" ? a.querySelector("h2")?.textContent : a?.textContent) ?? "").trim().slice(0, 60)}`;
    },
  };
  window.V = V;
};
const viewsStep = (fn) => run(`() => { if (!window.T) (${tablesHelpers})(); if (!window.V) (${viewsHelpers})(); return (${fn})(); }`);

// Opens the section, then the Saved views panel by a click, and waits for its list.
const viewsOpenPanel = () => viewsStep(async () => {
  T.section("Tables and Graphs");
  await T.wait(() => T.settled(), "the table");
  V.by(".panel-buttons button", "Saved views").focus(); // as a mouse press does: the panel gives focus back to it
  V.by(".panel-buttons button", "Saved views").click();
  await T.wait(() => V.views() && !V.views().innerText.includes("Reading the saved views"), "the saved views");
  return true;
});

// Open a saved view from the panel; the line, the rows and the filter bar it leaves.
const viewsOpen = (name) => viewsStep(`async () => {
  const was = T.ids().join();
  V.item(${JSON.stringify(name)}).querySelector("button").click();
  await T.wait(() => !V.views() && T.settled() && V.line().includes("claims match") && T.ids().join() !== was
    && !document.querySelector(".count .hint"), "the view's rows");
  await new Promise((r) => setTimeout(r, 300));
  await T.wait(() => T.settled(), "the settled rows");
  return { line: V.line(), count: V.count(), ids: T.ids(), caption: T.caption(), tab: V.tab(), active: V.active(),
    company: V.chosen("Company"), metric: V.chosen("Metric"), notice: document.querySelector(".notice")?.innerText ?? null };
}`);

// save: keyboard on the panel, a save, the existing-name line, a save while a chip shows, a removal.
const viewsSave = async () => {
  const out = {};
  const step = viewsStep;
  await tablesReady();
  out.filtered = await step(async () => {
    T.section("Tables and Graphs");
    await T.wait(() => T.settled(), "the table");
    await T.wait(() => [...document.querySelectorAll(".choices label")].some((l) => l.textContent.trim() === "Acme"), "the companies");
    T.tick("Company", "Acme");
    T.tick("Metric", "Scope 1 emissions");
    await T.wait(() => V.chosen("Metric") === "1" && parseInt(V.line()) < 14 && T.settled() && T.ids().length === parseInt(V.line()),
      "Acme's Scope 1 rows");
    return { line: V.line(), ids: T.ids() };
  });
  // Keyboard: Enter opens the panel with focus on it, Escape closes it and focus is back on the button.
  await step(() => V.by(".panel-buttons button", "Saved views").focus());
  await press("Enter");
  out.opened = await step(async () => {
    await T.wait(() => V.views() && !V.views().innerText.includes("Reading the saved views"), "the panel");
    return { active: V.active(), expanded: V.by(".panel-buttons button", "Saved views").getAttribute("aria-expanded"),
      empty: V.views().querySelector(".hint")?.innerText ?? null };
  });
  await press("Escape");
  out.escaped = await step(() => ({ open: !!V.views(), active: V.active() }));
  await press("Tab");
  out.tabNext = await step(() => V.active());
  await step(() => V.by(".panel-buttons button", "Saved views").click());
  out.saved = await step(async () => {
    await T.wait(() => V.views()?.querySelector(".hint"), "the empty list");
    const f = V.views().querySelector("form.save");
    V.set(f.querySelector("input[name=name]"), "scope 1");
    V.set(f.querySelector("input[name=contributor]"), "ana");
    await T.wait(() => !f.querySelector("button[type=submit]").disabled, "an enabled Save");
    f.querySelector("button[type=submit]").click();
    await T.wait(() => V.items().length === 1, "the saved view in the list");
    return { items: V.items(), done: V.views().querySelector(".saved-done").innerText,
      name: f.querySelector("input[name=name]").value };
  });
  out.exists = await step(async () => {
    V.set(V.views().querySelector("form.save input[name=name]"), " scope 1 ");
    return (await T.wait(() => V.views().querySelector(".saved-note"), "the existing-name line")).innerText;
  });
  // A save while a chip shows: one row checked, shown in Graphs, then saved from there.
  out.chip = await step(async () => {
    V.set(V.views().querySelector("form.save input[name=name]"), "");
    T.rows()[0].querySelector("input.select-row").click();
    await T.wait(() => !document.querySelector(".transfer button").disabled, "an enabled transfer");
    document.querySelector(".transfer button").click();
    await T.wait(() => V.tab() === "Graphs" && V.chip(), "the chip in Graphs");
    const f = V.views().querySelector("form.save");
    V.set(f.querySelector("input[name=name]"), "with chip");
    const notes = [...V.views().querySelectorAll(".saved-note")].map((p) => p.innerText);
    f.querySelector("button[type=submit]").click();
    await T.wait(() => V.items().length === 2, "the second view");
    return { chip: V.chip(), notes, items: V.items() };
  });
  // Remove: Enter opens its form with focus in the key box; Escape closes it and focus is back on Remove.
  await step(() => [...V.item("with chip").querySelectorAll("button")].find((b) => b.textContent.trim() === "Remove").focus());
  await press("Enter");
  out.removeForm = await step(async () => {
    const box = await T.wait(() => V.item("with chip").querySelector("form input[name=contributor]"), "the remove form");
    return { active: document.activeElement === box, key: box.value };
  });
  await press("Escape");
  out.removeEscaped = await step(() => ({ form: !!V.item("with chip").querySelector("form"), active: V.active(), panel: !!V.views() }));
  await press("Enter");
  out.removed = await step(async () => {
    const b = await T.wait(() => V.by(".saved-view form button[type=submit]", "Remove with chip"), "the confirm button");
    b.click();
    await T.wait(() => V.items().length === 1, "the view gone");
    return { items: V.items(), done: V.views().querySelector(".saved-done").innerText, active: V.active() };
  });
  return out;
};

// questions: keyboard on the panel; the six questions and counts; different-values; a metric-over-time choice.
const viewsQuestions = async () => {
  const out = {};
  const step = viewsStep;
  await tablesReady();
  await step(async () => {
    T.section("Tables and Graphs");
    await T.wait(() => T.settled(), "the table");
    V.by(".panel-buttons button", "Questions").focus();
  });
  await press("Enter");
  out.opened = await step(async () => {
    await T.wait(() => V.questions()?.querySelector(".question-list"), "the questions");
    return { active: V.active(), questions: [...V.questions().querySelectorAll(".question-list > li")].map((li) => ({
      text: li.querySelector(".question").textContent, count: li.querySelector(".question-count").textContent })) };
  });
  await press("Escape");
  out.escaped = await step(() => ({ open: !!V.questions(), active: V.active() }));
  out.different = await step(async () => {
    V.by(".panel-buttons button", "Questions").click();
    (await T.wait(() => [...document.querySelectorAll(".question")].find((b) => b.textContent.startsWith("Where do two reports")),
      "the questions")).click();
    await T.wait(() => !V.questions() && V.tab() === "Graphs" && V.chosen("Comparison") === "1"
      && V.cy()?.nodes(".claim").length === parseInt(V.line()), "the different values in Graphs");
    return { line: V.line(), tab: V.tab(), comparison: V.chosen("Comparison"), nodes: V.cy().nodes(".claim").map((n) => n.id()).sort(),
      chip: V.chip() };
  });
  out.series = await step(async () => {
    V.by(".panel-buttons button", "Questions").click();
    const q = await T.wait(() => [...document.querySelectorAll(".question")].find((b) => b.textContent.startsWith("How did one figure")),
      "the questions");
    q.click();
    const first = await T.wait(() => document.querySelector(".question-choices button"), "the series choices");
    const choices = [...document.querySelectorAll(".question-choices button")].map((b) => b.textContent);
    const expanded = q.getAttribute("aria-expanded");
    first.click();
    await T.wait(() => !V.questions() && V.tab() === "Graphs" && V.chip() && V.cy()?.nodes(".point").length > 0, "the series in Graphs");
    return { choices, expanded, chip: V.chip(), line: V.line(), series: V.chosen("Series"), points: V.cy().nodes(".point").length,
      view: document.querySelector(".graph-views [aria-pressed=true]")?.textContent ?? null };
  });
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
} else if (mode?.startsWith("graphs")) {
  // Story 6.3: the Graphs tab on tests/gate_fixture.py (graphs, graphs-stale) or the 500-claim fixture of
  // tests/test_viewer_graphs.py (graphs-limit). Canvas clicks and keys go through the DevTools Input domain, every
  // request the page sends is logged, and the page helpers live in window.g.
  const requests = [];
  ws.addEventListener("message", (m) => {
    const d = JSON.parse(m.data);
    if (d.method === "Network.requestWillBeSent") requests.push(`${d.params.request.method} ${new URL(d.params.request.url).pathname}`);
  });
  await send("Network.enable", {});
  const call = (fn, arg) => run(`() => (${fn})(${JSON.stringify(arg ?? null)})`);
  const mouse = async ({ x, y }, clicks, between) => {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    for (let c = 1; c <= clicks; c++) {
      if (c > 1 && between) await between();
      await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: c });
      await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: c });
    }
  };
  const KEYS = { Tab: ["Tab", 9, ""], Enter: ["Enter", 13, "\r"], Space: ["Space", 32, " ", " "], ArrowDown: ["ArrowDown", 40, ""], ArrowUp: ["ArrowUp", 38, ""] };
  const key = async (k) => {
    const [code, keyCode, text, name = k] = KEYS[k];
    await send("Input.dispatchKeyEvent", { type: "keyDown", key: name, code, windowsVirtualKeyCode: keyCode, text });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key: name, code, windowsVirtualKeyCode: keyCode });
  };
  await run(async () => {
    // the new tab may still show about:blank: wait for the viewer, whose window then holds the helpers
    for (let i = 0; i < 200 && !document.querySelector(".shell"); i++) await new Promise((r) => setTimeout(r, 50));
    const wait = async (fn, what) => {
      for (let i = 0; i < 200; i++) {
        const v = fn();
        if (v) return v;
        await new Promise((r) => setTimeout(r, 100));
      }
      throw new Error(`timed out waiting for ${what}: ${document.querySelector(".records")?.innerText.slice(0, 1500)}`);
    };
    const byText = (sel, text) => [...document.querySelectorAll(sel)].find((b) => b.textContent.trim() === text);
    const choices = (field) =>
      [...document.querySelectorAll(".choices")].find((d) => d.querySelector("summary").innerText.startsWith(field));
    const tick = (field, starts) => [...choices(field).querySelectorAll("label")]
      .find((l) => l.textContent.trim().startsWith(starts)).querySelector("input").click();
    const canvas = () => document.querySelector(".graphs .canvas");
    const cy = () => canvas()?._cyreg?.cy; // Cytoscape keeps its instance on its container
    const shell = () => document.querySelector(".count-line")?.innerText ?? "";
    const graph = () => document.querySelector(".graph-count")?.innerText ?? "";
    const loaded = (re) => performance.getEntriesByType("resource").filter((e) => re.test(e.name)).map((e) => e.name);
    const where = (id) => { // the element's place on the screen, for a mouse event
      canvas().scrollIntoView({ block: "center" });
      const el = cy().getElementById(id);
      if (el.isEdge()) cy().fit(el.connectedNodes(), 60); // an edge to a leaf node, drawn large: tap near the leaf
      const [a, b] = el.isEdge() ? [el.source().renderedPosition(), el.target().renderedPosition()] : [];
      const p = el.isNode() ? el.renderedPosition() : { x: a.x + 0.7 * (b.x - a.x), y: a.y + 0.7 * (b.y - a.y) };
      const r = canvas().getBoundingClientRect();
      return { x: r.left + p.x, y: r.top + p.y };
    };
    const evidence = () => ({ shown: !document.querySelector("main").hidden,
      page: document.querySelector("main .page img")?.alt ?? null, box: !!document.querySelector("main rect.box-selected"),
      claim: document.querySelector("aside button.claim[aria-pressed=true]")?.textContent ?? null });
    const section = (words) => byText(".sections button", words).click();
    const view = (words) => byText(".graph-views button", words).click();
    const row = (id) => document.querySelector(`.graphs [data-el="${CSS.escape(id)}"]`);
    const ids = (sel) => [...document.querySelectorAll(`.graphs ${sel} [data-el]`)].map((b) => b.dataset.el);
    const drawn = (n) => cy() && cy().nodes().length > 0 && (n === undefined || cy().nodes(".claim, .point").length === n);
    // The tab body learns that it is hidden or shown from a ResizeObserver report; wait for that report, then give it
    // time to render. Without it a hide and a show can fall in one render, and the focus return waits for the next one.
    const seen = (shown) => new Promise((resolve) => {
      const o = new ResizeObserver(([e]) => {
        if (e.contentRect.width > 0 !== shown) return;
        o.disconnect();
        setTimeout(resolve, 300);
      });
      o.observe(document.querySelector(".graphs"));
    });
    window.g = { wait, byText, tick, cy, shell, graph, loaded, where, evidence, section, view, row, ids, drawn, seen };
  });
  const open = () => call(async () => {
    await g.wait(() => g.evidence().shown && g.evidence().page && g.evidence().box, "the page with the box");
    await g.seen(false);
    return g.evidence();
  });
  const back = () => call(async () => {
    g.section("Tables and Graphs");
    await g.wait(() => !document.querySelector(".records").hidden && g.cy(), "the Graphs tab again");
    await g.seen(true); // the tab body sees itself shown and puts focus back
    return { el: document.activeElement?.dataset?.el ?? null, nodes: g.cy().nodes().length };
  });
  if (mode === "graphs") {
    const first = await run(async () => {
      g.section("Tables and Graphs");
      await g.wait(() => g.shell(), "the count");
      await new Promise((r) => setTimeout(r, 500));
      const before = g.loaded(/cytoscape/);
      (await g.wait(() => g.byText(".tabs button", "Graphs"), "the tabs")).click();
      await g.wait(() => g.drawn(), "the neighbourhood graph");
      const c = g.cy(), canvas = document.querySelector(".graphs .canvas");
      const [nodes, edges] = [g.ids("table:nth-of-type(1)"), g.ids("table:nth-of-type(2)")];
      // G2: the Tables tab (story 6.2) for the same filter: its rows line and the version in its caption
      const tables = async (was) => {
        g.byText(".tabs button", "Tables").click();
        const line = () => document.querySelector(".tables-paging span")?.textContent ?? "";
        await g.wait(() => line() && line() !== was && !document.querySelector(".claims-table[aria-busy=true]"), "the Tables tab");
        const out = { rows: line(), caption: document.querySelector(".claims-table caption").textContent };
        (await g.wait(() => g.byText(".tabs button", "Graphs"), "the tabs")).click();
        await g.wait(() => g.drawn(), "the Graphs tab");
        return out;
      };
      const tablesAll = await tables("");
      g.tick("Company", "Acme");
      await g.wait(() => g.shell().includes("9 claims") && g.drawn(9), "Acme's graph");
      const acme = { shell: g.shell(), graph: g.graph(), tables: await tables(tablesAll.rows) };
      g.tick("Company", "Acme");
      await g.wait(() => g.shell().includes("14 claims") && g.drawn(14), "every claim again");
      const text = document.querySelector(".graphs").innerText;
      return { before, after: g.loaded(/cytoscape/).length, shell: g.shell(), graph: g.graph(), tablesAll, acme,
        role: canvas.getAttribute("role"), label: canvas.getAttribute("aria-label"),
        tablesMatch: JSON.stringify(nodes.sort()) === JSON.stringify(c.nodes().map((n) => n.id()).sort())
          && JSON.stringify(edges.sort()) === JSON.stringify(c.edges().map((e) => e.id()).sort()),
        claimNodes: c.nodes(".claim").map((n) => n.id()).sort(), legend: document.querySelector(".legend").innerText,
        archived: document.querySelector(".count").innerText, text, grabbable: c.nodes()[0].grabbable() };
    });
    // A node and an edge by mouse: one tap selects and marks the row, a double-click opens the page with the box.
    const tap = async (id) => {
      await mouse(await call((i) => g.where(i), id), 1);
      return call(async (i) => {
        await g.wait(() => g.cy().$(":selected").length, "a selection");
        return { selected: g.cy().$(":selected").map((e) => e.id()), picked: g.row(i)?.classList.contains("picked") };
      }, id);
    };
    // The second click goes only once Cytoscape has handled the first as a tap.
    const dbl = async (id) => {
      await call(() => { window.tapped = false; g.cy().one("tap", () => { window.tapped = true; }); });
      await mouse(await call((i) => g.where(i), id), 2, () => call(() => g.wait(() => window.tapped, "the first tap")));
    };
    const nodeTap = await tap("claim:1");
    await dbl("claim:1");
    const node = await open();
    const nodeBack = await back();
    const edgeTap = await tap("claim:1>company:1");
    await dbl("claim:1>company:1");
    const edge = await open();
    await back();
    // Keyboard only: Tab onto the edge's row in the Edges table, Enter opens it; back again, focus is on that row.
    await call((i) => {
      const all = [...document.querySelectorAll(".graphs button")];
      all[all.indexOf(g.row(i)) - 1].focus();
    }, "claim:1>company:1");
    await key("Tab");
    const focused = await call(() => ({ el: document.activeElement.dataset.el, visible: document.activeElement.matches(":focus-visible"),
      selected: g.cy().$(":selected").map((e) => e.id()) }));
    await key("Enter");
    const keyboard = await open();
    const returned = await back();
    await key("ArrowDown");
    await key("ArrowDown");
    const arrows = await call(() => {
      g.section("Evidence");
      return g.evidence();
    });
    // P1: Space on two claim rows picks both, Tab past the rows between keeps what Space picked, Space again drops only
    // the second.
    // The picked rows (what Graphs hands to onSelectionChange) are logged once per change.
    await call(async () => {
      g.section("Tables and Graphs");
      await g.wait(() => g.cy(), "the graph");
      const picks = () => [...new Set([...document.querySelectorAll(".graphs .picked")].map((b) => b.dataset.el))].sort();
      window.picks = [];
      new MutationObserver(() => {
        const now = picks();
        if (JSON.stringify(now) !== JSON.stringify(window.picks.at(-1))) window.picks.push(now);
      }).observe(document.querySelector(".graphs"), { attributes: true, attributeFilter: ["class"], subtree: true });
      const all = [...document.querySelectorAll(".graphs button")];
      all[all.indexOf(g.row("claim:1")) - 1].focus();
    });
    const selected = () => call(() => g.cy().$(":selected").map((e) => e.id()).sort());
    const focus = () => call(() => document.activeElement.dataset.el);
    await key("Tab");
    await key("Space");
    for (let i = 0; i < 40 && (await focus()) !== "claim:2"; i++) await key("Tab"); // past the rows of claim 1's items
    await key("Space");
    const both = await selected();
    await key("Space");
    const spaced = { picks: await call(() => window.picks), both, after: await selected(), focus: await focus() };
    const rest = await call(async () => {
      g.section("Tables and Graphs");
      await g.wait(() => g.cy(), "the graph");
      const said = async (id) => {
        const was = document.querySelector(".graph-said")?.innerText;
        g.row(id).click();
        return g.wait(() => document.querySelector(".graph-said")?.innerText !== was
          && document.querySelector(".graph-said")?.innerText, `what ${id} says`);
      };
      g.row("cell:3:acme-meter!B2").click();
      const cell = (await g.wait(() => document.querySelector(".cell-view .marked[aria-current]"), "the marked cell")).innerText;
      g.byText(".cell-view button", "Close").click();
      const auditor = await said("auditor:1");
      const seriesNode = await said("series:2b7f0c7666c0");
      const stillHere = !document.querySelector(".records").hidden;
      g.row("comparison:2:5").click();
      const sides = [...(await g.wait(() => document.querySelector(".graph-choice"), "the two sides")).querySelectorAll("button")]
        .map((b) => b.innerText);
      g.view("Hypergraph");
      const asked = g.loaded(/\/api\/records/).length;
      await g.wait(() => g.cy()?.nodes(".hub").length, "the hypergraph");
      const c = g.cy();
      const hyper = { hubs: c.nodes(".hub").length, claims: c.nodes(".claim").length, rows: g.ids("tbody th").length,
        member: c.edges("[source = 'hub:1']").map((e) => e.target().id()).sort(), sameRequest: g.loaded(/\/api\/records/).length === asked };
      g.view("Time series");
      const noSeries = await g.wait(() => document.querySelector(".graph-reason")?.innerText, "the series reason");
      const noCanvas = !document.querySelector(".graphs .canvas");
      const series = async (label) => {
        g.tick("Series", label);
        await g.wait(() => g.cy()?.nodes(".point").length, `the time series of ${label}`);
        const c = g.cy();
        const rows = (n) => [...document.querySelectorAll(".graphs table")[n].querySelectorAll("tbody tr")].map((r) => r.innerText);
        const out = { points: rows(0), comparisons: rows(1), nodes: c.nodes().length,
          edges: c.edges().map((e) => [e.source().id(), e.target().id(), e.data("label"), e.hasClass("unresolved")]),
          x: Object.fromEntries(c.nodes().map((n) => [n.id(), [n.position("x"), n.position("y")]])) };
        g.tick("Series", label);
        await g.wait(() => !g.cy(), "the series cleared");
        return out;
      };
      const scope1 = await series("Acme: Scope 1 emissions, 4 points");
      const energy = await series("Acme: total energy, 4 points");
      g.view("Neighbourhood");
      g.tick("Company", "Acme");
      g.tick("Company", "Beta"); // two filter changes at once: only the newest answer is drawn
      await g.wait(() => g.drawn() && g.graph() === g.shell(), "the newest graph");
      const graphText = document.querySelector(".graphs").innerText;
      return { cell, auditor, seriesNode, stillHere, sides, hyper, noSeries, noCanvas, scope1, energy,
        newest: { shell: g.shell(), graph: g.graph() }, graphText };
    });
    out = { ...first, nodeTap, node, nodeBack, edgeTap, edge, focused, keyboard, returned, arrows, spaced, ...rest, requests };
  } else if (mode === "graphs-stale") {
    await run(async () => {
      g.section("Tables and Graphs");
      (await g.wait(() => g.byText(".tabs button", "Graphs"), "the tabs")).click();
      await g.wait(() => g.drawn(), "the graph");
    });
    const origin = new URL(url).origin;
    const auth = { Authorization: `Bearer ${new URL(url).searchParams.get("token")}` };
    const w = await fetch(`${origin}/api/claims/1/corrections`, {
      method: "POST",
      headers: { ...auth, "Content-Type": "application/json" },
      body: JSON.stringify({ value: "1,236", contributor: "ana", capacity: "analyst", rationale: "other tab" }),
    });
    out = { second_writer: w.status, ...(await run(async () => {
      g.view("Time series"); // a request of the Graphs tab alone: refused, the shell offers the new version
      const notice = (await g.wait(() => document.querySelector(".notice"), "the notice")).innerText;
      await new Promise((r) => setTimeout(r, 300));
      // F11 i1: the drawing on screen stays, labelled with its own version; nothing of the new version is drawn
      const kept = { drawn: g.drawn(14), graph: g.graph(), hint: document.querySelector(".graphs .hint")?.innerText ?? null };
      g.view("Neighbourhood");
      document.querySelector(".notice button").click();
      await g.wait(() => !document.querySelector(".notice") && g.drawn() && g.graph().includes("version 2")
        && g.shell().includes("version 2"), "the graph of version 2");
      return { notice, kept, graph: g.graph(), shell: g.shell() };
    })) };
  } else {
    out = await run(async () => {
      g.section("Tables and Graphs");
      (await g.wait(() => g.byText(".tabs button", "Graphs"), "the tabs")).click();
      const limit = await g.wait(() => document.querySelector(".graph-reason")?.innerText, "the limit text");
      const limitCanvas = !!document.querySelector(".graphs .canvas, .graphs table");
      const started = performance.now();
      g.tick("Document", "Big: big.pdf");
      await g.wait(() => g.drawn(500), "500 claims");
      const firstDraw = performance.now() - started;
      const c = g.cy();
      const layout = c.options().layout.name;
      const t = performance.now();
      c.layout({ name: "cose", animate: false }).run(); // how long cose alone holds the page
      const cose = performance.now() - t;
      const neighbourhood = { nodes: c.nodes().length, edges: c.edges().length, claims: c.nodes(".claim").length };
      const h0 = performance.now();
      g.view("Hypergraph");
      await g.wait(() => g.cy()?.nodes(".hub").length === 500, "the 500-claim hypergraph");
      const hyperDraw = performance.now() - h0;
      return { limit, limitCanvas, layout, firstDraw, cose, neighbourhood, hyperDraw, hyperLayout: g.cy().options().layout.name,
        hubs: g.cy().nodes(".hub").length, shell: g.shell(), graph: g.graph() };
    });
  }
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
} else if (mode === "transfer") {
  if (process.argv[5] === "limit") out = await transferLimit();
  else {
    out = await transferGate();
    const origin = new URL(url).origin;
    const auth = { Authorization: `Bearer ${new URL(url).searchParams.get("token")}` };
    const w = await fetch(`${origin}/api/claims/1/corrections`, {
      method: "POST",
      headers: { ...auth, "Content-Type": "application/json" },
      body: JSON.stringify({ value: "1,237", contributor: "ana", capacity: "analyst", rationale: "other tab" }),
    });
    out = { ...out, second_writer: w.status, ...(await transferStale()) };
  }
} else if (mode === "views") {
  if (process.argv[5] === "save") out = await viewsSave();
  else if (process.argv[5] === "questions") out = await viewsQuestions();
  else {
    // open, archived: the page pins the version current when it loads; for open, another writer then publishes, and
    // opening the view takes that version (B2: a view opens on the current version).
    await tablesReady();
    await viewsOpenPanel();
    let second_writer = null;
    if (process.argv[5] === "open") {
      const origin = new URL(url).origin;
      const auth = { Authorization: `Bearer ${new URL(url).searchParams.get("token")}` };
      const { claims } = await (await fetch(`${origin}/api/documents/1/claims`, { headers: auth })).json();
      second_writer = (await fetch(`${origin}/api/claims/${claims[0].id}/corrections`, {
        method: "POST",
        headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify({ value: "1,235", contributor: "ana", capacity: "analyst", rationale: "other tab" }),
      })).status;
    }
    out = { second_writer, ...(await viewsOpen("scope 1")) };
  }
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
