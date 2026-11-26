// Prompt 959 (stage B, the body): drives the REAL chat page in a real Chromium for tests/test_stop_button_prompt959.py.
//
//   node browser_stop_driver_prompt959.js <page url> <the question to ask> <text the stop reply must contain> [rounds, default 1]
//
// Each round: it types the question, waits for the emergency-stop button, presses it TWICE quickly, waits for the stop reply and for the end of
// the answer. It prints ONE line of JSON: what the page looked like before / while / after (of the LAST round), every POST the page made, and the
// bubbles.
// The test decides what is right; this file only observes. Exit codes: 0 done, 3 Playwright is not installed, 4 Chromium would not start
// (the test skips in both cases), 1 anything else (the test fails and shows the output).
"use strict";

const path = require("path");
const [url, question, expected, roundsText] = process.argv.slice(2);
const rounds = parseInt(roundsText || "1", 10);

function loadPlaywright() {
  try {
    return require("playwright");
  } catch (first) {
    const root = process.env.PLAYWRIGHT_ROOT;
    if (root) {
      try {
        return require(path.join(root, "playwright"));
      } catch (second) {
        return null;
      }
    }
    return null;
  }
}

async function state(page) {
  return page.evaluate(() => {
    const visible = (el) => !!el && !el.hidden && getComputedStyle(el).display !== "none" && el.getBoundingClientRect().width > 0;
    const stop = document.getElementById("stop-btn");
    const send = document.getElementById("send-btn");
    return {
      stopVisible: visible(stop),
      stopDisabled: stop.disabled,
      stopText: stop.textContent.trim(),
      stopType: stop.type,
      sendVisible: visible(send),
      sendDisabled: send.disabled,
      busy: document.getElementById("input-form").getAttribute("aria-busy"),
    };
  });
}

(async () => {
  const playwright = loadPlaywright();
  if (!playwright) {
    console.log(JSON.stringify({ error: "no_playwright" }));
    process.exit(3);
  }
  let browser;
  try {
    browser = await playwright.chromium.launch();
  } catch (e) {
    console.log(JSON.stringify({ error: "launch_failed", detail: String(e).slice(0, 300) }));
    process.exit(4);
  }
  const result = { posts: [] };
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "fa-IR" });
    const page = await context.newPage();
    page.on("request", (req) => {
      if (req.method() === "POST") result.posts.push({ path: new URL(req.url()).pathname, body: req.postData() });
    });
    await page.goto(url);
    await page.waitForSelector("#input-box");
    result.before = await state(page);

    for (let round = 1; round <= rounds; round++) {
      await page.fill("#input-box", question);
      await page.click("#send-btn");
      await page.waitForSelector("#stop-btn:not([hidden])", { timeout: 10000 });
      result.busy = await state(page);

      await page.dblclick("#stop-btn");               // two quick presses: only ONE stop word may go out
      await page.waitForFunction(
        ([text, count]) => Array.from(document.querySelectorAll("#messages .bubble")).filter((b) => b.textContent.includes(text)).length >= count,
        [expected, round],
        { timeout: 20000 }
      );
      await page.waitForSelector("#stop-btn", { state: "hidden", timeout: 20000 });   // this answer is over: the button goes away
      await page.waitForSelector("#send-btn:not([disabled])", { timeout: 20000 });
      result.after = await state(page);
    }
    result.bubbles = await page.$$eval("#messages .message:not(.typing)", (els) =>
      els.map((e) => ({ role: e.className, text: e.querySelector(".bubble").textContent }))
    );
    console.log(JSON.stringify(result));
    await browser.close();
    process.exit(0);
  } catch (e) {
    result.error = String(e).slice(0, 500);
    try {
      result.state = await state((await browser.contexts())[0].pages()[0]);
    } catch (ignored) {
      // the page may be gone: the error above is what matters
    }
    console.log(JSON.stringify(result));
    try {
      await browser.close();
    } catch (ignored) {
      // nothing to close
    }
    process.exit(1);
  }
})();
