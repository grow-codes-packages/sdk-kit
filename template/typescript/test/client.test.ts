import { inspect } from "node:util";
import { afterEach, describe, expect, it } from "vitest";
import {
  ConfigError,
  PACKAGE_KEY,
  REDACTED,
  RetryPolicy,
  Secret,
  VENDOR_ENV,
  __SERVICE__Client,
  __SERVICE__Config,
  __SERVICE__Error,
} from "../src/index.js";
import { type MockServer, closedPort, startServer } from "./helpers/server.js";

const servers: MockServer[] = [];
afterEach(async () => {
  await Promise.all(servers.splice(0).map((s) => s.close()));
});

async function demoServer(token = "t0ken-value"): Promise<MockServer> {
  const s = await startServer((req) => {
    if (req.url === "/health") return { status: 200, body: { status: "ok", version: "1.2.3" } };
    if (req.url === "/version") return { status: 200, body: { version: "1.2.3" } };
    if (req.url === "/v1/ping") {
      return req.headers.authorization === `Bearer ${token}`
        ? { status: 200, body: { pong: true } }
        : { status: 401, body: { message: "bad token" } };
    }
    return { status: 404 };
  });
  servers.push(s);
  return s;
}

const fast = { retry: { maxRetries: 1, initialBackoffMs: 1 } };

describe("__SERVICE__Config", () => {
  it("uses defaults and freezes", () => {
    const c = new __SERVICE__Config();
    expect(c.url).toBe(__SERVICE__Config.DEFAULT_URL);
    expect(c.requestTimeoutMs).toBe(30_000);
    expect(c.retry).toBeInstanceOf(RetryPolicy);
    expect(c.token).toBeUndefined();
    expect(Object.isFrozen(c)).toBe(true);
    expect(__SERVICE__Config.from(c)).toBe(c);
    expect(__SERVICE__Config.from().url).toBe(c.url);
    const prefix = `GROW_${PACKAGE_KEY.toUpperCase().replaceAll("-", "_")}_`;
    expect(__SERVICE__Config.ENV_PREFIX).toBe(prefix);
  });

  it("keeps optional settings", () => {
    const hooks = {};
    const logger = { debug() {}, info() {}, warn() {}, error() {} };
    const c = new __SERVICE__Config({
      proxy: "http://p:1",
      userAgentSuffix: "s",
      hooks,
      logger,
      token: new Secret("abcd"),
    });
    expect(c.proxy).toBe("http://p:1");
    expect(c.userAgentSuffix).toBe("s");
    expect(c.hooks).toBe(hooks);
    expect(c.logger).toBe(logger);
    expect(c.knownSecrets()).toEqual(["abcd"]);
  });

  it("validate() raises ConfigError", () => {
    expect(() => new __SERVICE__Config({ url: "ftp://x" })).toThrow(ConfigError);
    expect(() => new __SERVICE__Config({ token: "   " })).toThrow(ConfigError);
  });

  it("core.redaction.config: toString/JSON/inspect hide credentials", () => {
    const c = new __SERVICE__Config({
      token: "super-secret-tok",
      headers: { "x-api-key": "hdr-secret" },
    });
    for (const form of [String(c), JSON.stringify(c), inspect(c), `${c.token}`]) {
      expect(form).not.toContain("super-secret-tok");
      expect(form).not.toContain("hdr-secret");
    }
    expect(String(c)).toContain(REDACTED);
    expect(String(c)).toMatch(/Config\(/);
    expect(new __SERVICE__Config().toJSON().token).toBeNull();
  });

  it("core.config.env-precedence: explicit > GROW_* > vendor > default", () => {
    const prefix = __SERVICE__Config.ENV_PREFIX;
    const vendor = VENDOR_ENV as { url: string[]; token: string[] };
    const saved = { url: vendor.url, token: vendor.token };
    vendor.url = ["VENDOR_ADDR"];
    vendor.token = ["VENDOR_TOKEN"];
    try {
      const env = {
        [`${prefix}URL`]: "http://grow:1",
        VENDOR_ADDR: "http://vendor:2",
        VENDOR_TOKEN: "vendor-token",
        [`${prefix}REQUEST_TIMEOUT`]: "5s",
        [`${prefix}MAX_RETRIES`]: "7",
      };
      const fromEnv = __SERVICE__Config.fromEnv({}, env);
      expect(fromEnv.url).toBe("http://grow:1");
      expect(fromEnv.token?.reveal()).toBe("vendor-token");
      expect(fromEnv.requestTimeoutMs).toBe(5000);
      expect(fromEnv.retry.maxRetries).toBe(7);
      expect(fromEnv.connectTimeoutMs).toBe(10_000);

      const vendorOnly = __SERVICE__Config.fromEnv({}, { VENDOR_ADDR: "http://vendor:2" });
      expect(vendorOnly.url).toBe("http://vendor:2");

      const explicit = __SERVICE__Config.fromEnv(
        { url: "http://explicit:3", token: "explicit-token", retry: { initialBackoffMs: 1 } },
        env,
      );
      expect(explicit.url).toBe("http://explicit:3");
      expect(explicit.token?.reveal()).toBe("explicit-token");
      expect(explicit.retry.maxRetries).toBe(7);
      expect(explicit.retry.initialBackoffMs).toBe(1);

      expect(__SERVICE__Config.fromEnv({}, {}).url).toBe(__SERVICE__Config.DEFAULT_URL);
      expect(__SERVICE__Config.fromEnv().url).toBeTypeOf("string");

      let err: unknown;
      try {
        __SERVICE__Config.fromEnv({}, { [`${prefix}TOTAL_TIMEOUT`]: "forever-and-secret" });
      } catch (e) {
        err = e;
      }
      expect(err).toBeInstanceOf(ConfigError);
      expect((err as Error).message).toContain(`${prefix}TOTAL_TIMEOUT`);
      expect((err as Error).message).not.toContain("forever-and-secret");
    } finally {
      vendor.url = saved.url;
      vendor.token = saved.token;
    }
  });
});

describe("__SERVICE__Client", () => {
  it("health, ping and serverVersion against the demo API", async () => {
    const s = await demoServer();
    const client = new __SERVICE__Client({ url: s.url, token: "t0ken-value", ...fast });
    expect(await client.health()).toEqual({
      healthy: true,
      status: "ok",
      details: { version: "1.2.3" },
    });
    expect(await client.ping()).toBeGreaterThanOrEqual(0);
    expect(await client.serverVersion()).toBe("1.2.3");
    expect(client.transport.userAgent).toContain(`grow-codes-${PACKAGE_KEY}/`);
    await client.close();
  });

  it("ping with a bad token raises AuthenticationError without leaking it", async () => {
    const s = await demoServer();
    const client = new __SERVICE__Client(
      new __SERVICE__Config({ url: s.url, token: "wrong-token-xyz", ...fast }),
    );
    const err = await client.ping().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(__SERVICE__Error);
    expect((err as __SERVICE__Error).code).toBe("AUTHENTICATION");
    expect((err as Error).message).not.toContain("wrong-token-xyz");
    await client.close();
  });

  it("serverVersion raises UnsupportedError when absent", async () => {
    const s = await startServer([{ status: 404 }]);
    servers.push(s);
    const client = new __SERVICE__Client({ url: s.url, ...fast });
    await expect(client.serverVersion()).rejects.toMatchObject({ code: "UNSUPPORTED" });
    const s2 = await startServer([{ status: 200, body: { other: 1 } }]);
    servers.push(s2);
    const client2 = new __SERVICE__Client({ url: s2.url, ...fast });
    await expect(client2.serverVersion()).rejects.toMatchObject({ code: "UNSUPPORTED" });
    await client.close();
    await client2.close();
  });

  it("health reports vendor words and unhealthy statuses", async () => {
    const s = await startServer((req) =>
      req.url === "/health"
        ? { status: 200, body: { status: "degraded" } }
        : { status: 200, body: "" },
    );
    servers.push(s);
    const degraded = new __SERVICE__Client({ url: s.url, ...fast });
    expect(await degraded.health()).toMatchObject({ healthy: false, status: "degraded" });
    await degraded.close();
    const empty = await startServer([{ status: 200 }]);
    servers.push(empty);
    const ok = new __SERVICE__Client({ url: empty.url, ...fast });
    expect(await ok.health()).toMatchObject({ healthy: true, status: "ok" });
    await ok.close();
    const down = await startServer([{ status: 500 }]);
    servers.push(down);
    const sick = new __SERVICE__Client({ url: down.url, ...fast });
    expect(await sick.health()).toMatchObject({ healthy: false, status: "unhealthy" });
    await sick.close();
  });

  it("core.health.unreachable: closed port -> healthy=false, status=unreachable", async () => {
    const port = await closedPort();
    const client = new __SERVICE__Client({ url: `http://127.0.0.1:${port}`, ...fast });
    expect(await client.health()).toEqual({
      healthy: false,
      status: "unreachable",
      details: { error: "UNAVAILABLE" },
    });
    await client.close();
  });

  it("health rethrows cancellation", async () => {
    const s = await demoServer();
    const client = new __SERVICE__Client({ url: s.url });
    await expect(client.health({ signal: AbortSignal.abort() })).rejects.toMatchObject({
      code: "CANCELLED",
    });
    await client.close();
  });

  it("core.close.idempotent: close twice is safe", async () => {
    const s = await demoServer();
    const client = new __SERVICE__Client({ url: s.url });
    await client.health();
    await client.close();
    await client.close();
    await expect(client.ping()).rejects.toMatchObject({ code: "CONFIG" });
  });

  it("fromEnv builds from GROW_* variables", async () => {
    const s = await demoServer();
    const key = `${__SERVICE__Config.ENV_PREFIX}URL`;
    process.env[key] = s.url;
    try {
      const client = __SERVICE__Client.fromEnv({ token: "t0ken-value" });
      expect(client.config.url).toBe(s.url);
      expect(await client.ping()).toBeGreaterThanOrEqual(0);
      await client.close();
    } finally {
      delete process.env[key];
    }
  });
});
