import assert from "node:assert/strict";
import test from "node:test";

import { displayCount } from "../src/index.ts";

test("zero remains a visible count", () => {
  assert.equal(displayCount(0), "0");
});
