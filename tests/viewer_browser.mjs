// Drives the viewer in a headless Chrome over the DevTools protocol (Node's global WebSocket, no packages).
// usage: node viewer_browser.mjs <chrome debugging port> <viewer url>; prints one JSON object.
const [port, url] = process.argv.slice(2);

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

let r;
for (let i = 0; i < 50; i++) {
  r = await send("Runtime.evaluate", { expression: `(${page})()`, awaitPromise: true, returnByValue: true });
  if (r.result) break; // an error here: the new tab has no page to run in yet
  await new Promise((ok) => setTimeout(ok, 100));
}
ws.close();
if (!r.result || r.result.exceptionDetails) {
  console.error(JSON.stringify(r));
  process.exit(1);
}
console.log(JSON.stringify(r.result.result.value));
