// Optional real-browser checks; Node 22+ and an isolated Chromium CDP instance.
const assert = require("node:assert/strict");
const [base, port, scenario = "cancel"] = process.argv.slice(2);

async function main() {
  assert.match(base, /^http:\/\/127\.0\.0\.1:\d+$/);
  assert.equal((await fetch(base + "/api/health")).status, 200);
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const target = targets.find(item => item.type === "page");
  assert.ok(target);
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, {once: true});
    socket.addEventListener("error", reject, {once: true});
  });
  let sequence = 0;
  const pending = new Map(), urls = [];
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.method === "Network.requestWillBeSent") urls.push(message.params.request.url);
    if (pending.has(message.id)) {
      const {resolve, reject, timer} = pending.get(message.id);
      clearTimeout(timer);
      pending.delete(message.id);
      message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result);
    }
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, {resolve, reject, timer});
    socket.send(JSON.stringify({id, method, params}));
  });
  const evaluate = async expression => {
    const response = await call("Runtime.evaluate", {expression, awaitPromise: true, returnByValue: true});
    if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
    return response.result.value;
  };
  const wait = async expression => {
    for (let attempt = 0; attempt < 100; attempt++) {
      if (await evaluate(expression)) return;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error(`Browser condition timed out: ${expression}`);
  };
  try {
    await call("Network.enable");
    await call("Page.navigate", {url: base});
    await wait("document.readyState === 'complete' && typeof invalidate === 'function'");
    if (scenario === "cancel") {
      await evaluate(`window.__realFetch = window.fetch;
        window.fetch = (...args) => new Promise(resolve => {
          window.__release = async () => resolve(await window.__realFetch(args[0], {...args[1], signal: undefined}));
        });
        document.getElementById('match').click()`);
      await wait("typeof window.__release === 'function'");
      assert.equal(await evaluate("document.getElementById('cards').getAttribute('aria-busy')"), "true");
      await call("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27});
      assert.equal(await evaluate("document.getElementById('cancel').hidden"), true);
      assert.equal(await evaluate("document.activeElement.id"), "match");
      await evaluate("window.__release()");
      await new Promise(resolve => setTimeout(resolve, 200));
      assert.equal(await evaluate("document.querySelectorAll('#cards article').length"), 0);
      assert.equal(await evaluate("document.getElementById('cards').getAttribute('aria-busy')"), "false");
      assert.match(await evaluate("document.getElementById('status').textContent"), /canceled/);
    } else {
      throw new Error("Unknown browser scenario");
    }
    assert.ok(urls.every(url => url.startsWith(base + "/")), JSON.stringify(urls));
    assert.equal(await evaluate("window.localStorage.length + window.sessionStorage.length"), 0);
    console.log(`PASS real Chromium ${scenario}; ${urls.length} loopback requests; no browser storage`);
  } finally {
    socket.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
