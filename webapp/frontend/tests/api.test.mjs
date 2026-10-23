import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

function moduleURL(source) {
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  return `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
}

function componentModuleURL(source) {
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.React,
    },
  });
  return `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
}

const stringsURL = moduleURL(await readFile(new URL("../src/i18n/strings.ts", import.meta.url), "utf8"));
const { getLang, setLang } = await import(stringsURL);
const source = (await readFile(new URL("../src/api.ts", import.meta.url), "utf8"))
  .replace('from "./i18n/strings"', `from "${stringsURL}"`);
const { ApiError, classifyRaw, uploadInvoice } = await import(moduleURL(source));

const reactURL = moduleURL(
  "export const useState = () => []; export default { createElement: (...args) => args };",
);
const detailPanelURL = moduleURL("export function DetailPanel() { return null; }");
const resultTableSource = (await readFile(
  new URL("../src/components/ResultTable.tsx", import.meta.url), "utf8",
))
  .replace(
    'import { useState } from "react";',
    'import React, { useState } from "react";',
  )
  .replace('from "react"', `from "${reactURL}"`)
  .replace('from "../i18n/strings"', `from "${stringsURL}"`)
  .replace('from "./DetailPanel"', `from "${detailPanelURL}"`);
const { createCodeReview, isValidHsCode } = await import(componentModuleURL(resultTableSource));

const trade = { trade_mode: "import", origin_country: "ES", dispatch_country: "CN" };
const invoice = { filename: "text", source: "raw", items_count: 0, items: [], trade };
const ready = { type: "ready", total: 2, invoice };
const item = (index) => ({
  type: "item", index,
  item: {
    line_number: index + 1, description: `algodón ${index}`,
    classification: { status: "error", result: null, error: "test result" },
  },
});
const encode = (event) => new TextEncoder().encode(JSON.stringify(event) + "\n");
const response = (body) => new Response(body, {
  headers: { "content-type": "application/x-ndjson" },
});

test("decodes split UTF-8 and shows out-of-order completions in original order", async (t) => {
  const bytes = new TextEncoder().encode(
    [{ type: "stage", stage: "parsing" }, ready, item(1), item(0), { type: "done" }]
      .map(JSON.stringify).join("\n"),
  );
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    assert.equal(options.headers.accept, "application/x-ndjson");
    return response(new ReadableStream({
      start(controller) {
        for (let offset = 0; offset < bytes.length; offset += 7) {
          controller.enqueue(bytes.slice(offset, offset + 7));
        }
        controller.close();
      },
    }));
  });
  const updates = [];
  const result = await classifyRaw("algodón", trade, (progress) => updates.push(progress));
  assert.deepEqual(result.items.map((entry) => entry.line_number), [1, 2]);
  assert.deepEqual(result.trade, trade);
  assert.equal(result.items[0].description, "algodón 0");
  assert.deepEqual(updates.map((entry) => entry.completed), [0, 0, 1, 2, 2]);
  assert.equal(updates.at(-1).stage, "done");
});

test("publishes an item before the stream finishes", async (t) => {
  let finish;
  let reportFirst;
  const received = new Promise((resolve) => { reportFirst = resolve; });
  t.mock.method(globalThis, "fetch", async () => response(new ReadableStream({
    start(controller) {
      controller.enqueue(encode(ready));
      controller.enqueue(encode(item(1)));
      finish = () => {
        controller.enqueue(encode(item(0)));
        controller.enqueue(encode({ type: "done" }));
        controller.close();
      };
    },
  })));
  let finished = false;
  const request = classifyRaw("shirts", trade, (progress) => {
    if (progress.completed === 1) reportFirst(progress);
  }).then((result) => {
    finished = true;
    return result;
  });
  const progress = await received;
  assert.equal(finished, false);
  assert.equal(progress.invoice.items[0].line_number, 2);
  finish();
  assert.equal((await request).items.length, 2);
});

test("reports a streamed timeout without discarding already received results", async (t) => {
  t.mock.method(globalThis, "fetch", async () => response(
    [ready, item(0), { type: "error", status: 504, message: "deadline exceeded" }]
      .map(JSON.stringify).join("\n") + "\n",
  ));
  const updates = [];
  await assert.rejects(
    classifyRaw("shirts", trade, (progress) => updates.push(progress)),
    (error) => error instanceof ApiError && error.status === 504,
  );
  assert.equal(updates.at(-1).invoice.items.length, 1);
  assert.equal(updates.at(-1).completed, 1);
});

test("rejects truncated streams and false completion", async (t) => {
  for (const events of [[ready, item(0)], [ready, item(0), { type: "done" }]]) {
    t.mock.method(globalThis, "fetch", async () => response(events.map(JSON.stringify).join("\n")));
    await assert.rejects(
      classifyRaw("shirts", trade, () => {}),
      (error) => error instanceof ApiError && error.status === 502,
    );
    t.mock.restoreAll();
  }
});

test("rejects duplicate or out-of-range item indices", async (t) => {
  for (const events of [[ready, item(0), item(0)], [ready, item(2)]]) {
    t.mock.method(globalThis, "fetch", async () => response(events.map(JSON.stringify).join("\n")));
    await assert.rejects(
      classifyRaw("shirts", trade, () => {}),
      (error) => error instanceof ApiError && error.status === 502,
    );
    t.mock.restoreAll();
  }
});

test("rejects a ready event without valid trade details", async (t) => {
  const invalidReady = {
    type: "ready",
    total: 0,
    invoice: { ...invoice, trade: { ...trade, origin_country: "invalid" } },
  };
  t.mock.method(globalThis, "fetch", async () => response(
    [invalidReady, { type: "done" }].map(JSON.stringify).join("\n"),
  ));
  await assert.rejects(
    classifyRaw("shirts", trade, () => {}),
    (error) => error instanceof ApiError && error.status === 502,
  );
});

test("validates and tracks reviewed tariff codes", () => {
  assert.equal(isValidHsCode("620311"), true);
  assert.equal(isValidHsCode("62031"), false);
  assert.equal(isValidHsCode("62031A"), false);
  assert.deepEqual(createCodeReview("620311", "620311"), {
    code: "620311",
    changed: false,
  });
  assert.deepEqual(createCodeReview("610910", "620311"), {
    code: "610910",
    changed: true,
  });
});

test("sends the selected website language for text and invoice uploads", async (t) => {
  const original = getLang();
  t.after(() => setLang(original));
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify(invoice), { headers: { "content-type": "application/json" } });
  });
  for (const language of ["es", "en"]) {
    setLang(language);
    await classifyRaw("cotton shirts", trade);
    await uploadInvoice(new Blob(["cotton shirts"], { type: "text/plain" }), trade);
    assert.equal(JSON.parse(requests.at(-2).options.body).language, language);
    assert.deepEqual(JSON.parse(requests.at(-2).options.body).trade, trade);
    assert.equal(requests.at(-1).options.body.get("language"), language);
    assert.equal(requests.at(-1).options.body.get("trade_mode"), trade.trade_mode);
    assert.equal(requests.at(-1).options.body.get("origin_country"), trade.origin_country);
    assert.equal(requests.at(-1).options.body.get("dispatch_country"), trade.dispatch_country);
  }
});
