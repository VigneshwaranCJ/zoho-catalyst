// Run with: npm test   (Node's built-in test runner; Node 24 runs TypeScript directly)
import assert from "node:assert/strict";
import { test } from "node:test";

import { safeNextPath } from "./navigation.ts";

const ORIGIN = "http://localhost:3000";

test("keeps internal paths, including query and hash", () => {
  assert.equal(safeNextPath("/dashboard", ORIGIN), "/dashboard");
  assert.equal(safeNextPath("/knowledge?tab=drafts#top", ORIGIN), "/knowledge?tab=drafts#top");
});

test("falls back when next is missing", () => {
  assert.equal(safeNextPath(null, ORIGIN), "/dashboard");
  assert.equal(safeNextPath("", ORIGIN), "/dashboard");
});

test("rejects every way of pointing at another site", () => {
  for (const evil of [
    "//evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "https://evil.example/dashboard",
    "javascript:alert(1)",
    "http://localhost:3001/dashboard",
  ]) {
    assert.equal(safeNextPath(evil, ORIGIN), "/dashboard", `should reject ${evil}`);
  }
});

test("does not loop back to the login page", () => {
  assert.equal(safeNextPath("/login", ORIGIN), "/dashboard");
});
