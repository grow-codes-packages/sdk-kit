# @grow-codes/__KEY__

TypeScript SDK for [__DISPLAY__](https://grow-codes-packages.github.io/__KEY__/) by Grow Codes.
Node.js 22.12 or newer, ESM and CommonJS, full type definitions.

```sh
npm install @grow-codes/__KEY__
```

```ts
import { __SERVICE__Client } from "@grow-codes/__KEY__";

// Reads GROW___KEY_UPPER___URL, GROW___KEY_UPPER___TOKEN, timeouts, TLS and proxy settings.
const client = __SERVICE__Client.fromEnv();
try {
  console.log(await client.health()); // { healthy: true, status: "ok", details: {} }
  console.log(`ping: ${(await client.ping()).toFixed(1)} ms`);
} finally {
  await client.close();
}
```

Every error is a `__SERVICE__Error` subclass with a canonical `code` (`NOT_FOUND`,
`AUTHENTICATION`, `RATE_LIMITED`, …), `httpStatus`, `requestId` and `retryable`. Credentials
never appear in messages, logs, hook data or `toString()` output.

Test helpers (in-memory fakes and the conformance runner) live in
`@grow-codes/__KEY__/testing`.

Documentation: https://grow-codes-packages.github.io/__KEY__/ · Licence: Apache-2.0.
__DISPLAY__ is a trademark of __VENDOR__; this package is not affiliated with or endorsed by it.
