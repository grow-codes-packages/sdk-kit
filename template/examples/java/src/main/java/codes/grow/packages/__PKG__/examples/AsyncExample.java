// Created by sdk-kit __SDK_KIT_VERSION__; owned by this repository.
package codes.grow.packages.__PKG__.examples;

import codes.grow.packages.__PKG__.__SERVICE__Client;
import codes.grow.packages.__PKG__.core.HealthStatus;
import java.time.Duration;
import java.util.concurrent.CompletableFuture;

/** The {@code …Async} methods: run calls concurrently and cancel a slow one. */
public final class AsyncExample {
  private AsyncExample() {}

  /**
   * Runs the example.
   *
   * @param args unused
   */
  public static void main(String[] args) {
    try (var client = __SERVICE__Client.fromEnv()) {
      CompletableFuture<HealthStatus> health = client.healthAsync();
      CompletableFuture<Duration> ping = client.pingAsync();
      CompletableFuture.allOf(health, ping.exceptionally(e -> null)).join();
      System.out.println("health: " + health.join());
      ping.whenComplete(
          (latency, error) ->
              System.out.println(error == null ? "ping: " + latency : "ping failed: " + error));

      // Cancelling a future aborts the HTTP exchange and any pending retry.
      CompletableFuture<String> version = client.serverVersionAsync();
      version.cancel(true);
      System.out.println("version cancelled: " + version.isCancelled());
    }
  }
}
