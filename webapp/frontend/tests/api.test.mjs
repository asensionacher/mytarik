import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

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
const apiURL = moduleURL(source);
const {
  ApiError, answerClarification, classifyRaw, uploadInvoice, evaluateCustomsOperation,
  resolveTaricCodes,
} = await import(apiURL);

const customsSource = (await readFile(
  new URL("../src/components/CustomsPanel.tsx", import.meta.url), "utf8",
))
  .replace('import { useState } from "react";', 'import React, { useState } from "react";')
  .replace('from "react"', `from "${import.meta.resolve("react")}"`)
  .replace('from "../api"', `from "${apiURL}"`)
  .replace('from "../i18n/strings"', `from "${stringsURL}"`);
const { CustomsPanel, buildOperationPayload } = await import(componentModuleURL(customsSource));

const reactURL = moduleURL(
  "export const useState = () => []; export default { createElement: (...args) => args };",
);
const detailPanelURL = moduleURL("export function DetailPanel() { return null; }");
const clarificationPanelURL = moduleURL("export function ClarificationPanel() { return null; }");
const clarificationSource = (await readFile(
  new URL("../src/components/ClarificationPanel.tsx", import.meta.url), "utf8",
))
  .replace('import { useId, useState } from "react";', 'import React, { useId, useState } from "react";')
  .replace('from "react"', `from "${import.meta.resolve("react")}"`)
  .replace('from "../i18n/strings"', `from "${stringsURL}"`);
const { ClarificationPanel } = await import(componentModuleURL(clarificationSource));
const resultTableSource = (await readFile(
  new URL("../src/components/ResultTable.tsx", import.meta.url), "utf8",
))
  .replace(
    'import { useState } from "react";',
    'import React, { useState } from "react";',
  )
  .replace('from "react"', `from "${reactURL}"`)
  .replace('from "../i18n/strings"', `from "${stringsURL}"`)
  .replace('from "./DetailPanel"', `from "${detailPanelURL}"`)
  .replace('from "./ClarificationPanel"', `from "${clarificationPanelURL}"`);
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

test("sends product clarification history with original description, language and trade", async (t) => {
  setLang("es");
  const answers = [{ question: "¿Material?", answer: "Algodón" }];
  const classification = {
    status: "ambiguous",
    result: {
      clarification_question: { question: "¿Tejido?", options: ["Punto", "Plano"] },
      clarification_answers: answers,
    },
    error: null,
  };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/classify");
    assert.deepEqual(JSON.parse(options.body), {
      description: "Camisas", language: "es", trade, clarification_answers: answers,
    });
    return Response.json(classification);
  });
  assert.deepEqual(await answerClarification("Camisas", trade, answers), classification);
  setLang("en");
});

test("shows answer buttons and a free-text input, but never a fourth question", () => {
  setLang("es");
  const result = {
    clarification_answers: [{ question: "¿Material?", answer: "Algodón" }],
    clarification_question: { question: "¿Construcción?", options: ["Punto", "Plano"] },
  };
  const markup = renderToStaticMarkup(React.createElement(ClarificationPanel, {
    result, onAnswer: async () => {},
  }));
  assert.match(markup, /Pregunta 2 de un máximo de 3/);
  assert.match(markup, /type="button"[^>]*>Punto/);
  assert.match(markup, /type="button"[^>]*>Plano/);
  assert.match(markup, /<input/);
  assert.match(markup, /Algodón/);
  const exhausted = renderToStaticMarkup(React.createElement(ClarificationPanel, {
    result: {
      ...result, clarification_answers: [...result.clarification_answers, ...result.clarification_answers,
        ...result.clarification_answers], needs_human_review: true,
    },
    onAnswer: async () => {},
  }));
  assert.doesNotMatch(exhausted, /<input|<button/);
  assert.match(exhausted, /revisión humana/);
  setLang("en");
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

test("evaluates a customs operation against the public endpoint in the selected language", async (t) => {
  const original = getLang();
  t.after(() => setLang(original));
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url, options });
    return Response.json({ status: "ok", customs_regime: "IMPORT_FROM_THIRD_COUNTRY", items_measures: [] });
  });
  for (const language of ["es", "en"]) {
    setLang(language);
    const result = await evaluateCustomsOperation({
      operation_type: "IMPORT", origin_country: "CN", destination_country: "ES",
      items: [{ taric_code: "4011100000", description: "Neumáticos" }],
    });
    assert.equal(result.customs_regime, "IMPORT_FROM_THIRD_COUNTRY");
    const { url, options } = requests.at(-1);
    assert.equal(url, "/api/v1/customs/evaluate-operation");
    assert.equal(options.method, "POST");
    const body = JSON.parse(options.body);
    assert.equal(body.language, language);
    assert.equal(body.operation_type, "IMPORT");
    assert.equal(body.items[0].taric_code, "4011100000");
  }
});

test("resolves the TARIC codes of an HS heading through the public endpoint", async (t) => {
  const original = getLang();
  t.after(() => setLang(original));
  setLang("es");
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    return Response.json({
      hs_code: "610910", country: "ES",
      candidates: [
        { taric_code: "6109100010", description: "T-shirts", exact: true, source: "nomenclature" },
        { taric_code: "6109100090", description: "Other", exact: true, source: "nomenclature" },
      ],
      warnings: [], source: "access2markets",
    });
  });
  const result = await resolveTaricCodes("610910", "ES");
  assert.equal(requests[0].url, "/api/v1/customs/resolve-taric-codes");
  assert.deepEqual(requests[0].body, { hs_code: "610910", country: "ES", language: "es" });
  assert.deepEqual(result.candidates.map((c) => c.taric_code), ["6109100010", "6109100090"]);
});

test("maps the invoice context and the accepted codes to the customs operation contract", () => {
  const lines = [{
    index: 0,
    item: { description: "Camisetas de algodón", classification: { status: "classified", result: null, error: null } },
    hsCode: "610910",
  }];
  const trade = { trade_mode: "import", origin_country: "CN", dispatch_country: "ES" };
  const payload = buildOperationPayload(
    lines, { 0: "6109100010" }, { 0: { value: "1200.50", weight: "300" } }, trade,
  );
  assert.equal(payload.operation_type, "IMPORT");
  assert.equal(payload.origin_country, "CN");
  assert.equal(payload.destination_country, "ES");
  assert.equal(payload.items[0].taric_code, "6109100010");
  assert.equal(payload.items[0].customs_value, 1200.5);
  assert.equal(payload.items[0].currency, "EUR");
  assert.equal(payload.items[0].net_weight_kg, 300);

  const exportPayload = buildOperationPayload(
    lines, {}, {}, { trade_mode: "export", origin_country: "ES", dispatch_country: "MA" },
  );
  assert.equal(exportPayload.operation_type, "EXPORT");
  assert.equal(exportPayload.destination_country, "MA");
  assert.equal(exportPayload.items[0].taric_code, "610910");
  assert.equal(exportPayload.items[0].customs_value, undefined);
});

test("offers the customs measures only for the lines with a valid HS code", () => {
  setLang("es");
  const items = [
    { line_number: 1, description: "Camisetas", classification: { status: "classified", result: { primary_code: "610910" }, error: null } },
    { line_number: 2, description: "Error", classification: { status: "error", result: null, error: "boom" } },
  ];
  const markup = renderToStaticMarkup(React.createElement(CustomsPanel, {
    items,
    reviews: {},
    trade: { trade_mode: "import", origin_country: "CN", dispatch_country: "ES" },
    onError: () => {},
  }));
  assert.match(markup, /Evaluar medidas aduaneras/);
  assert.match(markup, /Medidas aduaneras/);
  setLang("en");
});
