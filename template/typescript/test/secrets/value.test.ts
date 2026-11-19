import { inspect } from "node:util";
import { describe, expect, it } from "vitest";
import { ValidationError } from "../../src/core/index.js";
import { SecretValue, encodeSecretInput } from "../../src/secrets/index.js";

describe("SecretValue", () => {
  it("reveals text, bytes and JSON", () => {
    const v = new SecretValue('{"a":1}', "3");
    expect(v.reveal()).toBe('{"a":1}');
    expect(v.json<{ a: number }>()).toEqual({ a: 1 });
    expect(new TextDecoder().decode(v.revealBytes())).toBe('{"a":1}');
    expect(v.version).toBe("3");
    expect(v.byteLength).toBe(7);
    expect(new SecretValue("x").version).toBeUndefined();
  });

  it("returns copies of the bytes", () => {
    const src = new Uint8Array([1, 2, 3]);
    const v = new SecretValue(src);
    src[0] = 9;
    const out = v.revealBytes();
    out[1] = 9;
    expect([...v.revealBytes()]).toEqual([1, 2, 3]);
  });

  it("throws ValidationError for non-UTF-8 or non-JSON values", () => {
    expect(() => new SecretValue(new Uint8Array([0xff, 0xfe])).reveal()).toThrow(ValidationError);
    expect(() => new SecretValue("not json").json()).toThrow(ValidationError);
  });

  it("never prints the value", () => {
    const v = new SecretValue("do-not-print");
    for (const form of [
      String(v),
      `${v}`,
      JSON.stringify({ v }),
      inspect(v),
      inspect({ nested: [v] }),
    ]) {
      expect(form).not.toContain("do-not-print");
    }
    expect(String(v)).toBe("SecretValue([REDACTED])");
  });

  it("encodes inputs and hashes", () => {
    expect(SecretValue.from({ a: 1 }).reveal()).toBe('{"a":1}');
    expect(SecretValue.from(new Uint8Array([104, 105]), "1").reveal()).toBe("hi");
    expect(new TextDecoder().decode(encodeSecretInput("x"))).toBe("x");
    expect(new SecretValue("a").sha256()).toBe(
      "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
    );
  });
});
