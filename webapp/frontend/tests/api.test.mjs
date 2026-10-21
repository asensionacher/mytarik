import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const { ApiError, classifyRaw } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

const invoice = { filename: "text", source: "raw", items_count: 0, items: [] };
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
  const result = await classifyRaw("algodón", (progress) => updates.push(progress));
  assert.deepEqual(result.items.map((entry) => entry.line_number), [1, 2]);
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
  const request = classifyRaw("shirts", (progress) => {
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
    classifyRaw("shirts", (progress) => updates.push(progress)),
    (error) => error instanceof ApiError && error.status === 504,
  );
  assert.equal(updates.at(-1).invoice.items.length, 1);
  assert.equal(updates.at(-1).completed, 1);
});

test("rejects truncated streams and false completion", async (t) => {
  for (const events of [[ready, item(0)], [ready, item(0), { type: "done" }]]) {
    t.mock.method(globalThis, "fetch", async () => response(events.map(JSON.stringify).join("\n")));
    await assert.rejects(
      classifyRaw("shirts", () => {}),
      (error) => error instanceof ApiError && error.status === 502,
    );
    t.mock.restoreAll();
  }
});

test("rejects duplicate or out-of-range item indices", async (t) => {
  for (const events of [[ready, item(0), item(0)], [ready, item(2)]]) {
    t.mock.method(globalThis, "fetch", async () => response(events.map(JSON.stringify).join("\n")));
    await assert.rejects(
      classifyRaw("shirts", () => {}),
      (error) => error instanceof ApiError && error.status === 502,
    );
    t.mock.restoreAll();
  }
});
