import { describe, expect, it } from "vitest";
import { InMemorySecretsProvider, type OpContext, secretsOps } from "../../src/testing/index.js";

function ctx(): OpContext & { cleanups: (() => unknown)[] } {
  const cleanups: (() => unknown)[] = [];
  return {
    scenario: { id: "x", category: "secrets", steps: [] },
    step: { op: "x" },
    run: "r",
    prefix: "p/",
    vars: {},
    capabilities: new Set(),
    substitute: <T>(v: T) => v,
    onCleanup: (fn) => cleanups.push(fn),
    cleanups,
  };
}

describe("secretsOps", () => {
  const ops = secretsOps.ops;

  it("passes options through", async () => {
    const p = new InMemorySecretsProvider();
    const c = ctx();
    expect(
      await ops.set?.(
        p,
        { name: "a", value: "1", path: "dir", cas: 0, tags: { t: "1" }, description: "d" },
        c,
      ),
    ).toBe("1");
    await ops.set?.(p, { name: "a", value: "2", path: "dir" }, c);
    expect(await ops.getString?.(p, { name: "a", path: "dir", version: "1" }, c)).toBe("1");
    expect(await ops.metadata?.(p, { name: "dir/a" }, c)).toMatchObject({
      tags: { t: "1" },
      extra: { description: "d" },
    });
    expect(await ops.list?.(p, { path: "dir" }, c)).toHaveLength(1);
    await ops.delete?.(p, { name: "a", path: "dir", versions: [2], permanent: false }, c);
    expect(await ops.getString?.(p, { name: "dir/a" }, c)).toBe("1");
    await ops.delete?.(p, { name: "dir/a", permanent: true }, c);
    expect(await ops.exists?.(p, { name: "dir/a" }, c)).toBe(false);
  });

  it("loadEnv with a mapping registers cleanup", async () => {
    const p = new InMemorySecretsProvider({ initial: { s: "v" } });
    const c = ctx();
    expect(
      await ops.loadEnv?.(p, { mapping: { GROW_TEST_SECRETS_OPS: "s" }, override: true }, c),
    ).toEqual({ GROW_TEST_SECRETS_OPS: "s" });
    expect(process.env.GROW_TEST_SECRETS_OPS).toBe("v");
    for (const fn of c.cleanups) await fn();
    expect(process.env.GROW_TEST_SECRETS_OPS).toBeUndefined();
  });

  it("validates arguments", async () => {
    const p = new InMemorySecretsProvider();
    const c = ctx();
    expect(() => ops.get?.(p, { name: 1 }, c)).toThrow('argument "name" must be a string');
    expect(() => ops.getMany?.(p, { names: "x" }, c)).toThrow('"names" must be an array');
    await expect(ops.loadEnv?.(p, {}, c)).rejects.toThrow('needs "path" or "mapping"');
    expect(await ops.getAll?.(p, {}, c)).toEqual(new Map());
  });
});
