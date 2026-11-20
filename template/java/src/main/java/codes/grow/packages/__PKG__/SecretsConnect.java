// Service-owned: generated once by sdk-kit, then maintained in this repository.
package codes.grow.packages.__PKG__;

import codes.grow.packages.__PKG__.core.UnsupportedException;
import codes.grow.packages.__PKG__.secrets.ConfigLoader.SecretsBootstrap;
import codes.grow.packages.__PKG__.secrets.ConfigLoader.SecretsConnection;
import codes.grow.packages.__PKG__.secrets.SecretsProvider;
import java.util.Map;

/** Connector of {@code ConfigLoader.load()} for __DISPLAY__. */
public final class SecretsConnect {
  private SecretsConnect() {}

  /**
   * Builds {@code __SERVICE__Client.fromEnv()} and returns its {@code secrets()} provider. Services that
   * log in (AppRole, ...) replace this method.
   *
   * @param bootstrap parsed GROW_SECRETS_* bootstrap
   * @param env environment the bootstrap was read from
   * @return the connection
   */
  public static SecretsConnection connect(SecretsBootstrap bootstrap, Map<String, String> env) {
    __SERVICE__Client client = __SERVICE__Client.fromEnv();
    try {
      Object provider = client.getClass().getMethod("secrets").invoke(client);
      return new SecretsConnection((SecretsProvider) provider, null, client::close);
    } catch (ReflectiveOperationException | ClassCastException e) {
      client.close();
      throw new UnsupportedException("loadConfig: __SERVICE__Client has no secrets() provider");
    }
  }
}
