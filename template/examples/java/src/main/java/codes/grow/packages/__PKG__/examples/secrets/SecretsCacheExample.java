// Created by sdk-kit __SDK_KIT_VERSION__; owned by this repository.
package codes.grow.packages.__PKG__.examples.secrets;

import codes.grow.packages.__PKG__.secrets.EnvLoader;
import codes.grow.packages.__PKG__.secrets.LoadEnvOptions;
import codes.grow.packages.__PKG__.secrets.SecretCache;
import codes.grow.packages.__PKG__.secrets.SecretValue;
import codes.grow.packages.__PKG__.secrets.WatchHandle;
import codes.grow.packages.__PKG__.testing.secrets.InMemorySecretsProvider;
import com.fasterxml.jackson.databind.JsonNode;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

/** Secrets helpers on any provider, shown with the in-memory provider from {@code testing}. */
public final class SecretsCacheExample {
  private SecretsCacheExample() {}

  /**
   * Runs the example.
   *
   * @param args unused
   * @throws InterruptedException when interrupted while waiting for the watch
   */
  public static void main(String[] args) throws InterruptedException {
    // Use the service's provider in real code; every provider has the same API.
    try (var provider = new InMemorySecretsProvider()) {
      provider.set("app/db-password", "s3cr3t");
      provider.set("app/port", "5432");
      provider.set("app/features", Map.of("beta", true));

      SecretCache cache =
          new SecretCache(
              provider,
              SecretCache.Options.builder()
                  .ttl(Duration.ofSeconds(30))
                  .staleWhileRevalidate(Duration.ofSeconds(10))
                  .build());
      SecretValue password = cache.require("app/db-password");
      System.out.println(password); // SecretValue([REDACTED])
      System.out.println(cache.getNumber("app/port") + " " + cache.getJson("app/features", JsonNode.class));
      System.out.println(cache.stats());

      // Java cannot change the process environment: loadEnv writes system properties by default.
      Map<String, String> env = new HashMap<>();
      LoadEnvOptions opts = LoadEnvOptions.builder().prefix("APP_").target(EnvLoader.map(env)).build();
      System.out.println(provider.loadEnv("app/", opts)); // names only, never values

      WatchHandle handle =
          provider.watch(
              "app/port",
              Duration.ofMillis(100),
              (now, before) -> System.out.println("port changed: " + now.map(SecretValue::reveal)));
      provider.set("app/port", "6543");
      Thread.sleep(300);
      handle.stop();
    }
  }
}
