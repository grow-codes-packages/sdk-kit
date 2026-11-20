package __PKG__

// Service-owned: generated once by sdk-kit, then maintained in this repository.

import "context"

// connectSecrets is the LoadConfig connector of this package: build a client from the
// GROW_SECRETS_* bootstrap (b.Addr, b.KVMount, AppRole b.RoleID/b.SecretID) and the package's own
// environment variables, log in when needed, and return the SecretsProvider to read the config
// keys from. Replace the body in the service repository.
func connectSecrets(_ context.Context, _ *SecretsBootstrap, _ map[string]string) (*SecretsConnection, error) {
	return nil, NewError(ErrorCodeUnsupported, errNoSecretsConnector.Error(), nil)
}
