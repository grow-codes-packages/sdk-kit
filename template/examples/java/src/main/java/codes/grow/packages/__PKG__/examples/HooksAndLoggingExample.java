// Created by sdk-kit __SDK_KIT_VERSION__; owned by this repository.
package codes.grow.packages.__PKG__.examples;

import codes.grow.packages.__PKG__.__SERVICE__Client;
import codes.grow.packages.__PKG__.core.EnvReader;
import codes.grow.packages.__PKG__.core.Hooks;
import codes.grow.packages.__PKG__.core.Logger;
import codes.grow.packages.__PKG__.core.RetryPolicy;
import java.time.Duration;
import java.util.Map;

/** Request hooks, a logger, retries and timeouts. URLs and headers in hooks are redacted. */
public final class HooksAndLoggingExample {
  private HooksAndLoggingExample() {}

  /**
   * Runs the example.
   *
   * @param args unused
   */
  public static void main(String[] args) {
    Hooks hooks =
        new Hooks() {
          @Override
          public void onRequest(RequestInfo info) {
            System.out.println("-> " + info.method() + " " + info.url() + " #" + info.attempt());
          }

          @Override
          public void onResponse(ResponseInfo info) {
            System.out.println("<- " + info.status() + " in " + info.durationMs() + " ms");
          }

          @Override
          public void onError(ErrorInfo info) {
            System.out.println("!! " + info.error().code() + " retry=" + info.willRetry());
          }
        };
    Logger logger =
        new Logger() {
          @Override
          public void debug(String message, Map<String, Object> fields) {
            System.out.println("debug: " + message + " " + fields);
          }
        };
    try (var client =
        __SERVICE__Client.builder()
            .fromEnv(EnvReader.system()) // explicit values below win over the environment
            .connectTimeout(Duration.ofSeconds(2))
            .requestTimeout(Duration.ofSeconds(5))
            .totalTimeout(Duration.ofSeconds(20))
            .retry(RetryPolicy.builder().maxRetries(5).initialBackoff(Duration.ofMillis(200)).build())
            .userAgentSuffix("hooks-example/1.0")
            .hooks(hooks)
            .logger(logger)
            .build()) {
      System.out.println(client.health());
    }
  }
}
