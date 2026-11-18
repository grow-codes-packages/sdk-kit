import { afterEach, describe, expect, it, vi } from "vitest";
import { ValidationError } from "../../src/core/index.js";
import { SecretValue, secretFingerprint, watchSecret } from "../../src/secrets/index.js";
import { InMemorySecretsProvider } from "../../src/testing/secrets-memory.js";

afterEach(() => {
  vi.useRealTimers();
});

describe("watch", () => {
  it("fingerprints by version, then by hash", () => {
    expect(secretFingerprint(null)).toBe("absent");
    expect(secretFingerprint(new SecretValue("x", "4"))).toBe("v:4");
    expect(secretFingerprint(new SecretValue("x", ""))).toMatch(/^h:/);
    expect(secretFingerprint(new SecretValue("x"))).toBe(secretFingerprint(new SecretValue("x")));
  });

  it("reports changes including deletion, and stops", async () => {
    vi.useFakeTimers();
    const p = new InMemorySecretsProvider({ initial: { s: "1" } });
    const changes: [string | null, string | null][] = [];
    const h = p.watch("s", 100, (n, o) => {
      changes.push([n?.reveal() ?? null, o?.reveal() ?? null]);
    });
    await h.ready;
    expect(p.activeWatchers).toBe(1);
    await vi.advanceTimersByTimeAsync(100);
    expect(changes).toEqual([]);
    await p.set("s", "2");
    await vi.advanceTimersByTimeAsync(100);
    expect(changes).toEqual([["2", "1"]]);
    await p.delete("s");
    await vi.advanceTimersByTimeAsync(100);
    expect(changes).toEqual([
      ["2", "1"],
      [null, "2"],
    ]);
    h.stop();
    h.stop();
    expect(h.stopped).toBe(true);
    expect(p.activeWatchers).toBe(0);
    await p.set("s", "3");
    await vi.advanceTimersByTimeAsync(500);
    expect(changes).toHaveLength(2);
  });

  it("detects value changes without versions via SHA-256", async () => {
    vi.useFakeTimers();
    let value = "a";
    const changes: string[] = [];
    const h = watchSecret(
      () => Promise.resolve(new SecretValue(value)),
      50,
      (n) => {
        changes.push(n?.reveal() ?? "null");
      },
    );
    await h.ready;
    value = "b";
    await vi.advanceTimersByTimeAsync(50);
    await vi.advanceTimersByTimeAsync(50);
    expect(changes).toEqual(["b"]);
    h.stop();
  });

  it("routes read errors and callback failures to onError and keeps polling", async () => {
    vi.useFakeTimers();
    let n = 0;
    const errors: unknown[] = [];
    const h = watchSecret(
      () => {
        n++;
        if (n === 1 || n === 3) return Promise.reject(new Error(`read ${n}`));
        return Promise.resolve(new SecretValue(String(n), String(n)));
      },
      10,
      () => {
        throw new Error("callback");
      },
      {
        onError: (e) => {
          errors.push((e as Error).message);
          throw new Error("ignored");
        },
      },
    );
    await h.ready;
    await vi.advanceTimersByTimeAsync(10);
    await vi.advanceTimersByTimeAsync(10);
    await vi.advanceTimersByTimeAsync(10);
    expect(errors).toEqual(["read 1", "read 3", "callback"]);
    h.stop();
    const silent = watchSecret(
      () => Promise.reject(new Error("x")),
      10,
      () => undefined,
    );
    await silent.ready;
    silent.stop();
  });

  it("ignores reads that finish after stop", async () => {
    let resolve: (v: SecretValue | null) => void = () => undefined;
    const onChange = vi.fn();
    const onError = vi.fn();
    const h = watchSecret(
      () =>
        new Promise<SecretValue | null>((r) => {
          resolve = r;
        }),
      10,
      onChange,
      { onError },
    );
    h.stop();
    resolve(null);
    await h.ready;
    expect(onChange).not.toHaveBeenCalled();
    const h2 = watchSecret(() => Promise.reject(new Error("late")), 10, onChange, { onError });
    h2.stop();
    await h2.ready;
    expect(onError).not.toHaveBeenCalled();
  });

  it("rejects bad intervals and close() stops every watcher", async () => {
    expect(() =>
      watchSecret(
        () => Promise.resolve(null),
        0,
        () => undefined,
      ),
    ).toThrow(ValidationError);
    const p = new InMemorySecretsProvider();
    const a = p.watch("x", 1000, () => undefined, { get: { path: "p" } });
    const b = p.watch("y", 1000, () => undefined);
    await Promise.all([a.ready, b.ready]);
    await p.close();
    await p.close();
    expect(a.stopped && b.stopped).toBe(true);
    expect(p.activeWatchers).toBe(0);
  });
});
