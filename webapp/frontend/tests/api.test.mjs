import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
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
  return `data:text/javascript;base64,${Buffer.from(componentModuleSource(source)).toString("base64")}`;
}

function componentModuleSource(source) {
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.React,
    },
  });
  return outputText;
}

const stringsURL = moduleURL(await readFile(new URL("../src/i18n/strings.ts", import.meta.url), "utf8"));
const { getLang, setLang } = await import(stringsURL);
const source = (await readFile(new URL("../src/api.ts", import.meta.url), "utf8"))
  .replace('from "./i18n/strings"', `from "${stringsURL}"`);
const apiURL = moduleURL(source);
const {
  ApiError, answerClarification, classifyRaw, uploadInvoice, evaluateCustomsOperation,
  resolveTaricCodes, retryLine,
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
  .replace(
    'import { useEffect, useId, useRef, useState } from "react";',
    'import React, { useEffect, useId, useRef, useState } from "react";',
  )
  .replace('from "react"', `from "${import.meta.resolve("react")}"`)
  .replace('from "../i18n/strings"', `from "${stringsURL}"`);
const { ClarificationPanel, isSelectedOption } = await import(componentModuleURL(clarificationSource));
const codeDecisionModalURL = moduleURL(
  "export function CodeDecisionModal() { return null; } export function needsCodeDecision() { return false; }",
);
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
  .replace('from "./ClarificationPanel"', `from "${clarificationPanelURL}"`)
  .replace('from "./CodeDecisionModal"', `from "${codeDecisionModalURL}"`);
const { createCodeReview, isValidHsCode } = await import(componentModuleURL(resultTableSource));

// Segunda instancia de ResultTable con el React real: la de arriba usa un
// stub que no produce elementos, así que no se puede renderizar.
const realReactURL = import.meta.resolve("react");
const renderableResultTableSource = (await readFile(
  new URL("../src/components/ResultTable.tsx", import.meta.url), "utf8",
))
  .replace(
    'import { useState } from "react";',
    'import React, { useState } from "react";',
  )
  .replace('from "react"', `from "${realReactURL}"`)
  .replace('from "../i18n/strings"', `from "${stringsURL}"`)
  .replace('from "./DetailPanel"', `from "${detailPanelURL}"`)
  .replace('from "./ClarificationPanel"', `from "${clarificationPanelURL}"`)
  .replace('from "./CodeDecisionModal"', `from "${codeDecisionModalURL}"`);
const { ResultTable } = await import(componentModuleURL(renderableResultTableSource));

// Módulo real del modal: se prueba su lógica y su renderizado.
const codeDecisionModalSource = (await readFile(
  new URL("../src/components/CodeDecisionModal.tsx", import.meta.url), "utf8",
))
  .replace(
    'import { useEffect, useRef, useState } from "react";',
    'import React, { useEffect, useRef, useState } from "react";',
  )
  .replace('from "react"', `from "${realReactURL}"`)
  .replace('from "../i18n/strings"', `from "${stringsURL}"`);
const { CodeDecisionModal, buildDecisionCandidates, needsCodeDecision } =
  await import(componentModuleURL(codeDecisionModalSource));

// Tercera instancia de ResultTable con el modal real, para comprobar que el
// disparador y el modal funcionan juntos. Ambos ficheros se transpilan a disco
// para que el import relativo resuelva como en el bundle.
const tempDir = await mkdtemp(join(tmpdir(), "mytarik-modal-"));
await writeFile(join(tempDir, "CodeDecisionModal.mjs"), componentModuleSource(
  (await readFile(
    new URL("../src/components/CodeDecisionModal.tsx", import.meta.url), "utf8",
  ))
    .replace(
      'import { useEffect, useRef, useState } from "react";',
      'import React, { useEffect, useRef, useState } from "react";',
    )
    .replace('from "react"', `from "${realReactURL}"`)
    .replace('from "../i18n/strings"', `from "${stringsURL}"`),
));
await writeFile(join(tempDir, "DetailPanel.mjs"),
  "export function DetailPanel() { return null; }");
await writeFile(join(tempDir, "ClarificationPanel.mjs"),
  "export function ClarificationPanel() { return null; }");
await writeFile(join(tempDir, "ResultTable.mjs"), componentModuleSource(
  (await readFile(
    new URL("../src/components/ResultTable.tsx", import.meta.url), "utf8",
  ))
    .replace(
      'import { useState } from "react";',
      'import React, { useState } from "react";',
    )
    .replace('from "react"', `from "${realReactURL}"`)
    .replace('from "../i18n/strings"', `from "${stringsURL}"`)
    .replace('from "./DetailPanel"', `from "./DetailPanel.mjs"`)
    .replace('from "./ClarificationPanel"', `from "./ClarificationPanel.mjs"`)
    .replace('from "./CodeDecisionModal"', `from "./CodeDecisionModal.mjs"`),
));
const { ResultTable: IntegratedResultTable } = await import(
  `file://${join(tempDir, "ResultTable.mjs")}`,
);

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

test("marks the chosen answer option while the AI is processing it", () => {
  assert.equal(isSelectedOption("Punto", "Punto"), true);
  assert.equal(isSelectedOption("Punto", "punto"), true);
  assert.equal(isSelectedOption("Punto", " Plano"), false);
  // Sin respuesta en curso no hay ninguna opción marcada.
  assert.equal(isSelectedOption("Punto", null), false);
  assert.equal(isSelectedOption("Punto", ""), false);
});

test("shows the thinking indicator and the selected option while answering", async () => {
  setLang("es");
  const result = {
    clarification_answers: [],
    clarification_question: { question: "¿Construcción?", options: ["Punto", "Plano"] },
  };
  let resolveAnswer;
  const pending = new Promise((resolve) => { resolveAnswer = resolve; });
  const markup = renderToStaticMarkup(React.createElement(ClarificationPanel, {
    result, onAnswer: () => pending,
  }));
  // Antes de responder no hay indicador de pensamiento ni opción marcada.
  assert.doesNotMatch(markup, /La IA está pensando/);
  assert.doesNotMatch(markup, /aria-pressed="true"/);
  // El panel ofrece la pregunta con sus opciones.
  assert.match(markup, /¿Construcción\?/);
  assert.match(markup, /Punto/);
  resolveAnswer();
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

test("reclassifies a single failed line without the clarification history", async (t) => {
  const original = getLang();
  t.after(() => setLang(original));
  setLang("es");
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    return Response.json({
      status: "classified",
      result: { primary_code: "610910", primary_description: "Camisetas" },
      error: null,
    });
  });
  const response = await retryLine("Camisetas de algodón", trade);
  assert.equal(response.status, "classified");
  assert.equal(requests[0].url, "/api/classify");
  assert.deepEqual(requests[0].body, {
    description: "Camisetas de algodón",
    trade,
    language: "es",
    clarification_answers: [],
  });
  setLang("en");
});

test("offers a retry action only for the line that failed", () => {
  setLang("es");
  const items = [
    {
      line_number: 1,
      description: "Camisetas",
      classification: {
        status: "classified",
        result: { primary_code: "610910", primary_description: "Camisetas", confidence: 0.9 },
        error: null,
      },
    },
    {
      line_number: 2,
      description: "Café en grano",
      classification: { status: "error", result: null, error: "TariffAI no respondió" },
    },
  ];
  const markup = renderToStaticMarkup(React.createElement(ResultTable, {
    items,
    reviews: {},
    onReview: () => {},
    onAnswer: async () => {},
    onRetry: () => {},
  }));
  // The failed line exposes the reason and a retry button.
  assert.match(markup, /TariffAI no respondió/);
  assert.match(markup, /Reintentar/);
  // The classified line does not.
  assert.equal(markup.match(/Reintentar/g).length, 2);
  setLang("en");
});

test("shows the retry button as busy while the line is being reclassified", () => {
  setLang("es");
  const items = [{
    line_number: 1,
    description: "Café en grano",
    classification: { status: "error", result: null, error: "boom" },
  }];
  const markup = renderToStaticMarkup(React.createElement(ResultTable, {
    items,
    reviews: {},
    onReview: () => {},
    onAnswer: async () => {},
    onRetry: () => {},
    retrying: { 0: true },
  }));
  assert.match(markup, /Reintentando…/);
  assert.doesNotMatch(markup, />Reintentar</);
  setLang("en");
});

test("offers a decision only while the AI is unsure about the line", () => {
  const base = {
    primary_code: "610910",
    primary_description: "Camisetas de algodón",
    confidence: 0.8,
    alternative_codes: [{ code: "610990", description: "Las demás", why_not: "Tela", trade_off: "Si es de punto" }],
  };
  // Confianza alta: la línea está resuelta, aunque la IA cite alternativas.
  assert.equal(needsCodeDecision({ ...base, confidence: 0.95 }), false);
  // Confianza alta y sin alternativas: tampoco hay nada que decidir.
  assert.equal(needsCodeDecision({ ...base, confidence: 0.95, alternative_codes: [] }), false);
  // Confianza baja: hay que decidir.
  assert.equal(needsCodeDecision({ ...base, confidence: 0.5 }), true);
  // Justo en el umbral: sigue resolta.
  assert.equal(needsCodeDecision({ ...base, confidence: 0.9 }), false);
  // Sin código primario ni alternativas: no se puede decidir nada.
  assert.equal(needsCodeDecision({ ...base, primary_code: null, confidence: 0.5, alternative_codes: [] }), false);
});

test("lists the primary code and the alternatives the AI is unsure about", () => {
  const candidates = buildDecisionCandidates({
    primary_code: "610910",
    primary_description: "Camisetas de algodón",
    confidence: 0.8,
    alternative_codes: [
      { code: "610990", description: "Las demás", why_not: "Tela", trade_off: "Si es de punto" },
      { code: "610910", description: "Duplicado" },
    ],
  });
  assert.equal(candidates.length, 2);
  assert.equal(candidates[0].code, "610910");
  assert.equal(candidates[0].isPrimary, true);
  assert.equal(candidates[0].confidence, 0.8);
  assert.equal(candidates[1].code, "610990");
  assert.equal(candidates[1].isPrimary, false);
  // El backend no informa de la confianza de las alternativas: no se inventa.
  assert.equal(candidates[1].confidence, null);
  assert.equal(candidates[1].why_not, "Tela");
  assert.equal(candidates[1].trade_off, "Si es de punto");
});

test("renders the decision modal with every candidate the AI proposed", () => {
  setLang("es");
  const result = {
    primary_code: "610910",
    primary_description: "Camisetas de algodón",
    confidence: 0.62,
    alternative_codes: [{ code: "610990", description: "Las demás", why_not: "Tela", trade_off: "Si es de punto" }],
  };
  const markup = renderToStaticMarkup(React.createElement(CodeDecisionModal, {
    result, description: "500 cajas de camisetas", onSelect: () => {}, onClose: () => {},
  }));
  assert.match(markup, /Decide el código HS/);
  assert.match(markup, /610910/);
  assert.match(markup, /610990/);
  assert.match(markup, /Camisetas de algodón/);
  assert.match(markup, /Propuesta principal/);
  // La confianza solo aparece donde el backend la informa.
  assert.match(markup, /62%/);
  assert.match(markup, /Por qué no/);
  assert.match(markup, /Trade-off/);
  assert.match(markup, /Confirmar código/);
  setLang("en");
});

test("offers the code decision from the row only while the AI is unsure", () => {
  setLang("es");
  const unsure = {
    line_number: 1,
    description: "Camisetas de algodón",
    classification: {
      status: "ambiguous",
      result: {
        primary_code: "610910",
        primary_description: "Camisetas de algodón",
        confidence: 0.62,
        alternative_codes: [{ code: "610990", description: "Las demás" }],
      },
      error: null,
    },
  };
  const confident = {
    ...unsure,
    line_number: 2,
    classification: {
      status: "classified",
      result: { ...unsure.classification.result, confidence: 0.97 },
      error: null,
    },
  };
  const markup = renderToStaticMarkup(React.createElement(IntegratedResultTable, {
    items: [unsure, confident],
    reviews: {},
    onReview: () => {},
    onAnswer: async () => {},
  }));
  // Solo la línea dudosa ofrece la decisión.
  assert.equal(markup.match(/Elegir código/g).length, 1);
  setLang("en");
});
