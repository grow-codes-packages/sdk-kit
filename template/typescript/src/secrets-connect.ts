// Service-owned: generated once by sdk-kit, then maintained in this repository.
// Connector used by `loadConfig()` (secrets/load-config.ts): builds a client from the
// `GROW_SECRETS_*` bootstrap and the package's own environment variables, logs in when the
// service needs it, and returns the SecretsProvider to read the config keys from.

import { UnsupportedError } from "./core/index.js";
import { __SERVICE__Client } from "./client.js";
import type { SecretsProvider } from "./secrets/types.js";
import type { SecretsBootstrap, SecretsConnection } from "./secrets/load-config.js";

/** A client that exposes its SecretsProvider as `secrets()` (the sdk-kit convention). */
interface WithSecrets {
  secrets?: () => SecretsProvider;
  secretsProvider?: () => SecretsProvider;
}

/**
 * Connects to __DISPLAY__ for `loadConfig()`. The default builds `__SERVICE__Client.fromEnv()` (the
 * address comes from `GROW_SECRETS_ADDR` when set) and uses `client.secrets()` (or `secretsProvider()`). Services that log in
 * (AppRole, …) replace this function.
 */
export async function connectSecrets(
  bootstrap: SecretsBootstrap,
  _env: Readonly<Record<string, string | undefined>>,
): Promise<SecretsConnection> {
  const overrides = bootstrap.addr === undefined ? {} : { url: bootstrap.addr };
  const client = __SERVICE__Client.fromEnv(overrides);
  const duck = client as unknown as WithSecrets;
  const secrets = duck.secrets ?? duck.secretsProvider;
  if (typeof secrets !== "function") {
    await client.close();
    throw new UnsupportedError("loadConfig: __SERVICE__Client has no secrets() provider");
  }
  return { provider: secrets.call(client), close: () => client.close() };
}
