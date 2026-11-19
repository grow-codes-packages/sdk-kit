// Created by sdk-kit __SDK_KIT_VERSION__; owned by this repository.
package codes.grow.packages.__PKG__.examples;

import codes.grow.packages.__PKG__.__SERVICE__Client;
import codes.grow.packages.__PKG__.core.AuthenticationException;
import codes.grow.packages.__PKG__.core.HealthStatus;
import codes.grow.packages.__PKG__.core.UnsupportedException;

/** Basics: configuration from the environment, health, ping, server version and errors. */
public final class BasicExample {
  private BasicExample() {}

  /**
   * Runs the example.
   *
   * @param args unused
   */
  public static void main(String[] args) {
    // Reads GROW___KEY_UPPER___URL, GROW___KEY_UPPER___TOKEN, timeouts, TLS and proxy settings.
    try (var client = __SERVICE__Client.fromEnv()) {
      HealthStatus health = client.health(); // never throws for an unreachable service
      System.out.println("health: " + health);
      if (!health.healthy()) {
        return;
      }
      try {
        System.out.println("ping: " + client.ping().toMillis() + " ms");
      } catch (AuthenticationException e) {
        // messages never contain the token
        System.out.println("bad credentials: " + e.getMessage());
      }
      try {
        System.out.println("server version: " + client.serverVersion());
      } catch (UnsupportedException e) {
        System.out.println("the server exposes no version");
      }
    }
  }
}
