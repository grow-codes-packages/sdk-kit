import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CancelledError, healthStatus, type HealthStatus } from "../../src/core/index.js";
import {
  type ConformanceOptions,
  type CoreTarget,
  conformanceCases,
  formatReport,
  runConformance,
} from "../../src/testing/index.js";

const scenariosDir = fileURLToPath(new URL("../../../conformance/scenarios/", import.meta.url));

/**
 * A fake core target: the runner and the `core` ops are tested without the client's real routes,
 * so the client can change freely. The client itself is covered by `test/client.test.ts` and the
 * integration suite.
 */
class FakeCoreTarget implements CoreTarget {
  closed = 0;

  #ensureOpen(op: string): void {
    if (this.closed > 0) throw new CancelledError(`${op}: client is closed`);
  }

  health(): Promise<HealthStatus> {
    this.#ensureOpen("health");
    return Promise.resolve(healthStatus("ok"));
  }

  ping(): Promise<number> {
    this.#ensureOpen("ping");
    return Promise.resolve(1);
  }

  serverVersion(): Promise<string> {
    this.#ensureOpen("serverVersion");
    return Promise.resolve("0.0.1");
  }

  close(): Promise<void> {
    this.closed += 1;
    return Promise.resolve();
  }
}

function options(): ConformanceOptions {
  return {
    scenariosDir,
    categories: ["core"],
    factories: { core: () => new FakeCoreTarget() },
    capabilities: { core: ["version"] },
  };
}

describe("conformance (core) against a fake core target", () => {
  it("every core scenario passes", async () => {
    const report = await runConformance(options());
    expect(report.failed, formatReport(report)).toBe(0);
    expect(report.skipped).toBe(0);
    expect(report.results.map((r) => r.id)).toContain("core.health");
  });

  for (const c of conformanceCases(options())) {
    it.skipIf(c.skip !== undefined)(`case ${c.id}`, async () => {
      expect((await c.run()).status).toBe("passed");
    });
  }
});
