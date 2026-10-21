import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/i18n/strings.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const moduleURL = `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
let version = 0;
const loadLanguage = () => import(`${moduleURL}#${version++}`);

function browser(t, cookie, language, protocol = "https:") {
  const names = ["document", "navigator", "location"];
  const originals = names.map((name) => Object.getOwnPropertyDescriptor(globalThis, name));
  Object.defineProperties(globalThis, {
    document: { configurable: true, value: { cookie } },
    navigator: { configurable: true, value: { language } },
    location: { configurable: true, value: { protocol } },
  });
  t.after(() => names.forEach((name, index) => {
    if (originals[index]) Object.defineProperty(globalThis, name, originals[index]);
    else delete globalThis[name];
  }));
}

test("restores the cookie instead of the browser language after reloading", async (t) => {
  browser(t, "other=value; mytarik.lang=es", "en-US");
  const first = await loadLanguage();
  assert.equal(first.getLang(), "es");
  first.setLang("en");
  const cookie = document.cookie;
  assert.match(cookie, /^mytarik\.lang=en;/);
  assert.match(cookie, /Path=\//);
  assert.match(cookie, /Max-Age=31536000/);
  assert.match(cookie, /SameSite=Lax/);
  assert.match(cookie, /; Secure$/);
  assert.equal((await loadLanguage()).getLang(), "en");
});

test("defaults to Spanish for missing or unsupported cookies even in an English browser", async (t) => {
  browser(t, "", "en-GB");
  assert.equal((await loadLanguage()).getLang(), "es");
  document.cookie = "mytarik.lang=fr";
  assert.equal((await loadLanguage()).getLang(), "es");
  document.cookie = "mytarik.lang=toString";
  assert.equal((await loadLanguage()).getLang(), "es");
});

test("persists language over local HTTP without a Secure-only cookie", async (t) => {
  browser(t, "", "es-ES", "http:");
  const language = await loadLanguage();
  language.setLang("en");
  assert.match(document.cookie, /^mytarik\.lang=en;/);
  assert.doesNotMatch(document.cookie, /Secure/);
  assert.equal(language.getLang(), "en");
  language.setLang("toString");
  assert.equal(language.getLang(), "en");
});
