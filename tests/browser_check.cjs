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
    throw new Error(`Browser condition timed out: ${expression}; ` + await evaluate(
      "JSON.stringify({url:location.href,status:document.getElementById('status')?.textContent,focus:document.activeElement.id})"));
  };
  try {
    await call("Network.enable");
    const pageUrl = base + "/?browserCheck=" + Date.now();
    await call("Page.navigate", {url: pageUrl});
    await wait(`location.href === ${JSON.stringify(pageUrl)} && document.readyState === 'complete' && typeof invalidate === 'function'`);
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
    } else if (scenario === "validation") {
      await evaluate(`window.__calls = 0; window.__realFetch = window.fetch;
        window.fetch = (...args) => { window.__calls++; return window.__realFetch(...args); };
        const stage = document.getElementById('stage');
        stage.add(new Option('not bounded', 'PERSONAL_VALUE')); stage.value = 'PERSONAL_VALUE';
        document.getElementById('match').click()`);
      assert.equal(await evaluate("window.__calls"), 0);
      assert.equal(await evaluate("document.activeElement.id"), "stage");
      assert.equal(await evaluate("document.getElementById('stage').getAttribute('aria-invalid')"), "true");
      assert.ok(!(await evaluate("document.getElementById('status').textContent")).includes("PERSONAL_VALUE"));
      assert.equal(await evaluate("document.getElementById('cards').getAttribute('aria-busy')"), "false");
      await evaluate(`document.getElementById('stage').value = 'pregnancy';
        document.getElementById('stage').dispatchEvent(new Event('change'));
        document.getElementById('match').click()`);
      await wait("document.querySelectorAll('#cards article').length === 3");
      assert.equal(await evaluate("document.getElementById('stage').hasAttribute('aria-invalid')"), false);
      assert.equal(await evaluate("window.__calls"), 1);
    } else if (scenario === "recovery") {
      await evaluate(`window.__realFetch = window.fetch; window.__first = true;
        window.fetch = async (...args) => { const result = await window.__realFetch(...args);
          if (window.__first) { window.__first = false; return new Response('{}', {status: 503}); }
          return result;
        };
        document.getElementById('match').click()`);
      await wait("!document.getElementById('retry').hidden");
      assert.match(await evaluate("document.getElementById('status').textContent"), /train.*restart/);
      assert.equal(await evaluate("document.querySelectorAll('#cards article').length"), 0);
      await evaluate("document.getElementById('retry').click()");
      await wait("document.querySelectorAll('#cards article').length === 3");
      assert.equal(await evaluate("document.getElementById('retry').hidden"), true);
      assert.equal(await evaluate("document.getElementById('match').disabled"), false);
    } else if (scenario === "navigation") {
      await evaluate("document.querySelector('.skip-link').focus()");
      await call("Input.dispatchKeyEvent", {type: "keyDown", key: "Enter", code: "Enter", text: "\r", windowsVirtualKeyCode: 13});
      await call("Input.dispatchKeyEvent", {type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13});
      assert.equal(await evaluate("document.activeElement.id"), "demo-title");
      await evaluate("document.getElementById('match').focus()");
      await call("Input.dispatchKeyEvent", {type: "keyDown", key: "Enter", code: "Enter", text: "\r", windowsVirtualKeyCode: 13});
      await call("Input.dispatchKeyEvent", {type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13});
      await wait("document.querySelectorAll('#cards article').length === 3");
      assert.equal(await evaluate("document.activeElement.id"), "results-title");
      await evaluate("document.querySelector('nav a[href=\"#planner-title\"]').focus()");
      await call("Input.dispatchKeyEvent", {type: "keyDown", key: "Enter", code: "Enter", text: "\r", windowsVirtualKeyCode: 13});
      assert.equal(await evaluate("document.activeElement.id"), "planner-title");
    } else if (scenario === "planner") {
      await evaluate("document.getElementById('match').click()");
      await wait("document.querySelectorAll('#cards article').length === 3");
      await evaluate("document.querySelectorAll('#cards input')[0].click(); document.querySelectorAll('#cards input')[1].click()");
      assert.equal(await evaluate("document.querySelectorAll('#question-list li').length"), 2);
      await evaluate("document.querySelector('#question-list button').click()");
      assert.equal(await evaluate("document.querySelectorAll('#question-list li').length"), 1);
      assert.equal(await evaluate("document.querySelectorAll('#cards input')[0].checked"), false);
      assert.equal(await evaluate("document.querySelectorAll('#cards input')[1].checked"), true);
      assert.equal(await evaluate("document.activeElement.closest('ol').id"), "question-list");
      await evaluate("document.getElementById('clear-questions').click()");
      assert.equal(await evaluate("document.querySelectorAll('#cards article').length"), 3);
      assert.equal(await evaluate("document.querySelectorAll('#cards input:checked').length"), 0);
      assert.equal(await evaluate("document.getElementById('print').disabled"), true);
      assert.equal(await evaluate("document.activeElement.id"), "planner-title");
    } else if (scenario === "ordering") {
      await evaluate("document.getElementById('match').click()");
      await wait("document.querySelectorAll('#cards article').length === 3");
      await evaluate("Array.from(document.querySelectorAll('#cards input')).slice(0, 3).forEach(input => input.click())");
      const original = await evaluate("Array.from(selected)");
      await evaluate("document.querySelectorAll('#question-list li')[2].querySelector('[data-action=\"up\"]').click()");
      assert.deepEqual(await evaluate("Array.from(selected)"), [original[0], original[2], original[1]]);
      assert.equal(await evaluate("document.activeElement.dataset.action"), "up");
      assert.equal(await evaluate("document.querySelector('#question-list li [data-action=\"up\"]').disabled"), true);
      assert.equal(await evaluate("document.querySelectorAll('#question-list li')[2].querySelector('[data-action=\"down\"]').disabled"), true);
      assert.equal(await evaluate("document.querySelectorAll('#cards input:checked').length"), 3);
    } else if (scenario === "provenance") {
      await evaluate("document.getElementById('match').click()");
      await wait("document.querySelectorAll('#cards article').length === 3");
      await evaluate("document.querySelector('#cards input').click()");
      const title = await evaluate("document.querySelector('#cards h3').textContent");
      assert.ok((await evaluate("document.querySelector('#question-list .question-source').textContent")).includes(title));
      assert.match(await evaluate("document.querySelector('#question-list .question-source').textContent"), /question 1/);
      assert.match(await evaluate("document.getElementById('planner-provenance').textContent"), /[0-9a-f]{64}$/);
      await evaluate("document.getElementById('clear').click()");
      assert.equal(await evaluate("questionSources.size"), 0);
      assert.equal(await evaluate("document.getElementById('planner-provenance').hidden"), true);
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
