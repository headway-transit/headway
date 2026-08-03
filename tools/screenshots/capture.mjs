/**
 * README screenshot capture for Headway.
 *
 * Drives a headless Chrome over the DevTools Protocol: signs in once, then
 * reaches every surface by CLICKING THE NAV — never by navigating to a URL.
 * The session token lives in memory only, so a page load after login lands
 * back on /login and would silently capture the sign-in screen instead of the
 * page you asked for. That mistake produced a set of useless screenshots once
 * before; this script is written so it cannot happen again.
 */
import WebSocket from "ws";

const BASE = process.env.SHOT_BASE || "http://127.0.0.1:8080";
const USER = process.env.SHOT_USER;
const PASS = process.env.SHOT_PASS;
const OUT = process.env.SHOT_OUT || ".";
const W = 1440, H = 960;

const shots = JSON.parse(process.env.SHOT_PLAN);

let ws, id = 0;
const pending = new Map();
const send = (method, params = {}, sessionId) =>
  new Promise((res, rej) => {
    const msgId = ++id;
    pending.set(msgId, { res, rej });
    ws.send(JSON.stringify({ id: msgId, method, params, sessionId }));
  });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function evaluate(expr) {
  const r = await send("Runtime.evaluate", {
    expression: expr,
    awaitPromise: true,
    returnByValue: true,
  });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " :: " + expr);
  return r.result?.value;
}

/** Click a nav link by its visible text — the only safe way to move around. */
async function clickNav(text) {
  const ok = await evaluate(`
    (() => {
      const wanted = ${JSON.stringify(text)}.toLowerCase();
      const el = [...document.querySelectorAll('a,button')]
        .find(e => (e.textContent||'').trim().toLowerCase() === wanted);
      if (!el) return false;
      el.click();
      return true;
    })()
  `);
  if (!ok) throw new Error(`nav link not found: ${text}`);
}

async function main() {
  const targets = await (await fetch("http://127.0.0.1:9333/json/list")).json();
  const page = targets.find((t) => t.type === "page");
  ws = new WebSocket(page.webSocketDebuggerUrl, { maxPayload: 256 * 1024 * 1024 });
  await new Promise((r) => ws.on("open", r));
  ws.on("message", (raw) => {
    const m = JSON.parse(raw);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
    }
  });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", {
    width: W, height: H, deviceScaleFactor: 2, mobile: false,
  });

  // --- sign in (the ONLY full navigation in this script) -------------------
  await send("Page.navigate", { url: `${BASE}/login` });
  await sleep(2500);
  await evaluate(`
    (() => {
      const set = (el, v) => {
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, v);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      };
      const inputs = [...document.querySelectorAll('input')];
      set(inputs[0], ${JSON.stringify(USER)});
      set(inputs[1], ${JSON.stringify(PASS)});
      document.querySelector('form').requestSubmit();
      return true;
    })()
  `);
  await sleep(4000);
  const landed = await evaluate("location.pathname");
  if (landed === "/login") throw new Error("sign-in failed — still on /login");
  console.log("signed in, landed on", landed);

  // --- theme ---------------------------------------------------------------
  if (process.env.SHOT_DARK === "1") {
    await evaluate(`
      (() => {
        const b = [...document.querySelectorAll('button')]
          .find(e => /switch to dark theme/i.test(e.textContent||''));
        if (b) b.click();
        return true;
      })()
    `);
    await sleep(800);
  }
  // dismiss the guided tour if it is showing
  await evaluate(`
    (() => {
      const s = [...document.querySelectorAll('a,button')]
        .find(e => /skip the tour/i.test(e.textContent||''));
      if (s) s.click();
      return true;
    })()
  `);
  await sleep(600);

  for (const shot of shots) {
    try {
      await clickNav(shot.nav);
      await sleep(shot.wait ?? 3500);
      if (shot.then) { await evaluate(shot.then); await sleep(shot.thenWait ?? 2500); }
      const { data } = await send("Page.captureScreenshot", {
        format: "png", captureBeyondViewport: false,
      });
      const fs = await import("node:fs");
      fs.writeFileSync(`${OUT}/${shot.file}`, Buffer.from(data, "base64"));
      const path = await evaluate("location.pathname");
      console.log(`  ✓ ${shot.file}  (${path})`);
    } catch (e) {
      console.log(`  ✗ ${shot.file}: ${e.message}`);
    }
  }
  ws.close();
}

main().catch((e) => { console.error("FAILED:", e.message); process.exit(1); });
