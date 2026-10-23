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
  const mouse = async ({ x, y }, clicks) => {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    for (let c = 1; c <= clicks; c++) {
      await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: c });
      await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: c });
    }
  };
  const KEYS = { Tab: ["Tab", 9, ""], Enter: ["Enter", 13, "\r"], ArrowDown: ["ArrowDown", 40, ""], ArrowUp: ["ArrowUp", 38, ""] };
  const key = async (k) => {
    const [code, keyCode, text] = KEYS[k];
    await send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code, windowsVirtualKeyCode: keyCode, text });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code, windowsVirtualKeyCode: keyCode });
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
    window.g = { wait, byText, tick, cy, shell, graph, loaded, where, evidence, section, view, row, ids, drawn };
  });
  const open = () => call(async () => {
    await g.wait(() => g.evidence().shown && g.evidence().page && g.evidence().box, "the page with the box");
    return g.evidence();
  });
  const back = () => call(async () => {
    g.section("Tables and Graphs");
    await g.wait(() => !document.querySelector(".records").hidden && g.cy(), "the Graphs tab again");
    await new Promise((r) => setTimeout(r, 300)); // the tab body sees itself shown and puts focus back
    return { el: document.activeElement?.dataset?.el ?? null, nodes: g.cy().nodes().length };
  });
  if (mode === "graphs") {
    const first = await run(async () => {
      g.section("Tables and Graphs");
      await g.wait(() => g.shell(), "the count");
      await new Promise((r) => setTimeout(r, 500));
      const before = g.loaded(/cytoscape/);
      g.byText(".tabs button", "Graphs").click();
      await g.wait(() => g.drawn(), "the neighbourhood graph");
      const c = g.cy(), canvas = document.querySelector(".graphs .canvas");
      const [nodes, edges] = [g.ids("table:nth-of-type(1)"), g.ids("table:nth-of-type(2)")];
      g.tick("Company", "Acme");
      await g.wait(() => g.shell().includes("9 claims") && g.drawn(9), "Acme's graph");
      const acme = { shell: g.shell(), graph: g.graph() };
      g.tick("Company", "Acme");
      await g.wait(() => g.drawn(14), "every claim again");
      const text = document.querySelector(".graphs").innerText;
      return { before, after: g.loaded(/cytoscape/).length, shell: g.shell(), graph: g.graph(), acme,
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
    const nodeTap = await tap("claim:1");
    await mouse(await call((i) => g.where(i), "claim:1"), 2);
    const node = await open();
    const nodeBack = await back();
    const edgeTap = await tap("claim:1>company:1");
    await mouse(await call((i) => g.where(i), "claim:1>company:1"), 2);
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
    out = { ...first, nodeTap, node, nodeBack, edgeTap, edge, focused, keyboard, returned, arrows, ...rest, requests };
  } else if (mode === "graphs-stale") {
    await run(async () => {
      g.section("Tables and Graphs");
      g.byText(".tabs button", "Graphs").click();
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
      await g.wait(() => !document.querySelector(".notice") && g.drawn() && g.graph().includes("version 2"), "the graph of version 2");
      return { notice, kept, graph: g.graph(), shell: g.shell() };
    })) };
  } else {
    out = await run(async () => {
      g.section("Tables and Graphs");
      g.byText(".tabs button", "Graphs").click();
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
