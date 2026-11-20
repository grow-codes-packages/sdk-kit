// Service-owned: generated once by sdk-kit, then maintained in this repository.

import { describe, expect, it } from "vitest";
import { ConfigError, UnsupportedError } from "../src/core/index.js";
import { connectSecrets } from "../src/secrets-connect.js";

describe("connectSecrets", () => {
  it("returns a provider or reports that the service has none", async () => {
    try {
      const connection = await connectSecrets(
        { addr: "http://127.0.0.1:1", path: "", auth: "" },
        {},
      );
      expect(typeof connection.provider.getAll).toBe("function");
      await connection.close();
    } catch (err) {
      expect(err instanceof UnsupportedError || err instanceof ConfigError).toBe(true);
    }
  });
});
