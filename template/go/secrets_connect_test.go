package __PKG__

// Service-owned: generated once by sdk-kit, then maintained in this repository.

import (
	"context"
	"errors"
	"testing"
)

// TestConnectSecretsDefault checks the connector without network I/O: it either returns a
// provider or reports UNSUPPORTED (or CONFIG when the service needs more settings).
func TestConnectSecretsDefault(t *testing.T) {
	conn, err := connectSecrets(context.Background(), &SecretsBootstrap{Addr: "http://127.0.0.1:1"}, map[string]string{})
	if err != nil {
		if !errors.Is(err, ErrUnsupported) && !errors.Is(err, ErrConfig) {
			t.Fatalf("unexpected error: %v", err)
		}
		return
	}
	if conn.Provider == nil {
		t.Fatal("nil provider")
	}
	if conn.Close != nil {
		_ = conn.Close()
	}
}
