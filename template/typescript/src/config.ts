// Service-owned: generated once by sdk-kit, then maintained in this repository.

import {
  type CommonConfig,
  type CommonConfigOptions,
  type CommonVendorEnv,
  ConfigError,
  type EnvMap,
  EnvReader,
  type Hooks,
  type ClientLogger,
  REDACTED,
  type RetryPolicy,
  Secret,
  type TlsOptions,
  describeCommonConfig,
  mergeOptions,
  readCommonEnv,
  resolveCommonConfig,
  secretValues,
  validateCommonConfig,
} from "./core/index.js";

const INSPECT = Symbol.for("nodejs.util.inspect.custom");

/** Port text from the stack catalog; the default URL uses its first number. */
const CATALOG_PORT = "__PORT__";

/** Options accepted by {@link __SERVICE__Config} (all optional). */
export interface __SERVICE__ConfigOptions extends CommonConfigOptions {
  /** API token sent as `Authorization: Bearer <token>` (env `GROW___KEY_UPPER___TOKEN`). */
  token?: string | Secret;
}

/**
 * Vendor environment variables read after `GROW___KEY_UPPER___*`, in order
 * (e.g. `BAO_ADDR` then `VAULT_ADDR`). Filled in by the service.
 */
export const VENDOR_ENV: CommonVendorEnv & { token: readonly string[] } = {
  url: [],
  token: [],
};

/** Immutable configuration of {@link __SERVICE__Client}. */
export class __SERVICE__Config implements CommonConfig {
  /** Default endpoint. */
  static readonly DEFAULT_URL = `http://127.0.0.1:${/\d+/.exec(CATALOG_PORT)?.[0] ?? "8080"}`;
  /** Prefix of every environment variable. */
  static readonly ENV_PREFIX = "GROW___KEY_UPPER___";

  readonly url: string;
  readonly connectTimeoutMs: number;
  readonly requestTimeoutMs: number;
  readonly totalTimeoutMs: number;
  readonly retry: RetryPolicy;
  readonly tls: Readonly<TlsOptions>;
  readonly proxy?: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly userAgentSuffix?: string;
  readonly hooks?: Hooks;
  readonly logger?: ClientLogger;
  /** API token. */
  readonly token?: Secret;

  /** Applies defaults, validates (throws {@link ConfigError}) and freezes. */
  constructor(options: __SERVICE__ConfigOptions = {}) {
    const common = resolveCommonConfig(options, __SERVICE__Config.DEFAULT_URL);
    this.url = common.url;
    this.connectTimeoutMs = common.connectTimeoutMs;
    this.requestTimeoutMs = common.requestTimeoutMs;
    this.totalTimeoutMs = common.totalTimeoutMs;
    this.retry = common.retry;
    this.tls = common.tls;
    this.headers = common.headers;
    if (common.proxy !== undefined) this.proxy = common.proxy;
    if (common.userAgentSuffix !== undefined) this.userAgentSuffix = common.userAgentSuffix;
    if (common.hooks !== undefined) this.hooks = common.hooks;
    if (common.logger !== undefined) this.logger = common.logger;
    const token = Secret.from(options.token);
    if (token !== undefined) this.token = token;
    this.validate();
    Object.freeze(this);
  }

  /** Returns `options` when it already is a config, otherwise builds one. */
  static from(options: __SERVICE__ConfigOptions = {}): __SERVICE__Config {
    if (options instanceof __SERVICE__Config) return options;
    return new __SERVICE__Config(options);
  }

  /**
   * Builds a config from the environment. Precedence: explicit `overrides` >
   * `GROW___KEY_UPPER___<NAME>` > vendor variables ({@link VENDOR_ENV}) > defaults.
   */
  static fromEnv(overrides: __SERVICE__ConfigOptions = {}, env: EnvMap = process.env) {
    const reader = new EnvReader(__SERVICE__Config.ENV_PREFIX, env);
    const fromEnv: __SERVICE__ConfigOptions = readCommonEnv(reader, VENDOR_ENV);
    const token = reader.secret("TOKEN", VENDOR_ENV.token);
    if (token !== undefined) fromEnv.token = token;
    const merged = mergeOptions<__SERVICE__ConfigOptions>(fromEnv, overrides);
    return new __SERVICE__Config(merged);
  }

  /** Throws {@link ConfigError} when a setting is invalid. Service rules go here. */
  validate(): void {
    validateCommonConfig(this);
    if (this.token?.reveal().trim() === "")
      throw new ConfigError("invalid configuration: token must not be blank");
  }

  /** Credential values to redact from error messages and logs. */
  knownSecrets(): string[] {
    return secretValues(this.token);
  }

  /** Debug form with every credential redacted. */
  toJSON(): Record<string, unknown> {
    return { ...describeCommonConfig(this), token: this.token === undefined ? null : REDACTED };
  }

  toString(): string {
    return `__SERVICE__Config(${JSON.stringify(this.toJSON())})`;
  }

  [INSPECT](): string {
    return this.toString();
  }
}
