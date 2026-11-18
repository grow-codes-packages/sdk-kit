// Runs the shared conformance scenarios (conformance/scenarios) against the real service.
// Service packages add their category factories (secrets/logging/tracing) and declare the
// capabilities they support; every skip must be justified in docs/compatibility.md.

import assert from "node:assert/strict";
import { before, test } from "node:test";
import { __SERVICE__Client } from "@grow-codes/__KEY__";
import { formatReport, runConformance } from "@grow-codes/__KEY__/testing";
import { loadBootstrapEnv, scenariosDir } from "./env.ts";

before(() => {
  loadBootstrapEnv();
});

test("conformance: core", async () => {
  const report = await runConformance({
    scenariosDir,
    categories: ["core"],
    factories: { core: () => __SERVICE__Client.fromEnv() },
    capabilities: { core: ["version"] },
  });
  console.log(formatReport(report));
  assert.equal(report.failed, 0, formatReport(report));
  assert.ok(report.passed > 0);
});
