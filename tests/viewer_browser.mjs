// Drives the viewer in a headless Chrome over the DevTools protocol (Node's global WebSocket, no packages).
// usage: node viewer_browser.mjs <chrome debugging port> <viewer url> [stale]; prints one JSON object.
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
} else {
  out = await run(page);
}
ws.close();
console.log(JSON.stringify(out));
