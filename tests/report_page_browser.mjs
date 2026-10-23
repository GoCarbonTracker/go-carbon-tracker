// Opens report viewer pages (story 7.5) in a headless Chrome over the DevTools protocol (Node's global WebSocket, no
// packages), one after another in one tab, and prints one JSON object: per page its innerText with every <details>
// open, title, script count, images and the table cells holding a GCT-INJECT plant; then every URL any page requested
// and every console log entry (a blocked request shows there as a Content Security Policy violation).
// The inject field serves story 7.5's plant test: the text and element count of each row cell (tr.row > td) and
// spreadsheet cell (table.cell th, td) whose text holds GCT-INJECT; other callers can ignore it.
// usage: node report_page_browser.mjs <chrome debugging port> <page url> [<page url> ...]
const [port, ...urls] = process.argv.slice(2);

const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok) => (ws.onopen = ok));
let next = 0;
let loaded = () => {};
const waiting = new Map();
const requests = [];
const log = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.method === "Network.requestWillBeSent") requests.push(d.params.request.url);
  if (d.method === "Log.entryAdded") log.push(d.params.entry.text);
  if (d.method === "Page.loadEventFired") loaded();
  if (d.id && waiting.has(d.id)) {
    waiting.get(d.id)(d);
    waiting.delete(d.id);
  }
};
const send = (method, params = {}) =>
  new Promise((ok) => {
    waiting.set(++next, ok);
    ws.send(JSON.stringify({ id: next, method, params }));
  });
const evaluate = async (expression) =>
  (await send("Runtime.evaluate", { expression, returnByValue: true })).result.result.value;

await send("Network.enable");
await send("Page.enable");
await send("Log.enable");
const pages = [];
for (const url of urls) {
  const done = new Promise((ok, fail) => {
    loaded = ok;
    setTimeout(() => fail(new Error(`timed out loading ${url}`)), 30000);
  });
  await send("Page.navigate", { url });
  await done;
  await evaluate("document.querySelectorAll('details').forEach((d) => (d.open = true)); 0");
  pages.push(
    await evaluate(`({
      url: location.href,
      title: document.title,
      text: document.body.innerText,
      scripts: document.scripts.length,
      images: [...document.images].map((i) => ({ src: i.getAttribute("src"), complete: i.complete, width: i.naturalWidth })),
      inject: [...document.querySelectorAll("tr.row > td, table.cell th, table.cell td")]
        .filter((c) => c.textContent.includes("GCT-INJECT"))
        .map((c) => ({ text: c.textContent, children: c.childElementCount })),
    })`),
  );
}
console.log(JSON.stringify({ pages, requests, log }));
ws.close();
await fetch(`http://127.0.0.1:${port}/json/close/${target.id}`).catch(() => {});
