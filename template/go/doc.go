// Package __PKG__ is the Grow Codes SDK for __DISPLAY__.
//
// Create a client from the environment (GROW___KEY_UPPER___URL,
// GROW___KEY_UPPER___TOKEN, ...) or from a Config literal:
//
//	client, err := __PKG__.NewClientFromEnv()
//	if err != nil {
//		return err
//	}
//	defer client.Close()
//	status, err := client.Health(ctx)
//
// Every error is an *Error; compare codes with errors.Is against the Err*
// sentinels (errors.Is(err, __PKG__.ErrNotFound)). Credentials are wrapped in
// Secret and never appear in errors, hooks or logs.
//
// __DISPLAY__ is a trademark of __VENDOR__. This package is not affiliated
// with or endorsed by __VENDOR__.
package __PKG__
