// Wording helpers (src/lib/text.ts). Run with `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { inSentence, listInSentence } from "./text.ts";

test("a title inside a sentence keeps its names and acronyms", () => {
  assert.equal(inSentence("Told when Jeron is off"), "told when Jeron is off");
  assert.equal(inSentence("API token"), "API token");
  assert.equal(inSentence("NSE history"), "NSE history");
  assert.equal(inSentence("Jeron's login"), "Jeron's login");
  assert.equal(inSentence("Holiday calendar"), "holiday calendar");
  assert.equal(inSentence("A"), "a");
  assert.equal(inSentence(""), "");
});

test("titles join into a sentence", () => {
  assert.equal(listInSentence([]), "");
  assert.equal(listInSentence(["News"]), "news");
  assert.equal(listInSentence(["News", "API token"]), "news and API token");
  assert.equal(listInSentence(["News", "Holiday calendar", "API token"]), "news, holiday calendar and API token");
});
