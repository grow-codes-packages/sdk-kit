// Created by sdk-kit __SDK_KIT_VERSION__; owned by this repository.
//! Integration suite against the real service (Docker): client round trips and the
//! conformance scenarios for `core` and this service's categories.

use grow___KEY_SNAKE__ as sdk;
use grow___KEY_SNAKE___integration as support;
use sdk::testing::{ConformanceRunner, CoreHandler};
use sdk::ErrorCode;
use support::{conformance_dir, load_bootstrap_env};

use sdk::blocking::__SERVICE__Client as BlockingClient;

use sdk::__SERVICE__Client as Client;
use sdk::__SERVICE__Config as Config;

fn client() -> Client {
    load_bootstrap_env();
    Client::new(Config::from_env().expect("config from env")).expect("client")
}

#[tokio::test]
async fn client_round_trip() {
    let c = client();
    let health = c.health().await.expect("health");
    assert!(health.healthy, "service not healthy: {health:?}");
    c.ping().await.expect("authenticated ping");
    match c.server_version().await {
        Ok(v) => assert!(!v.is_empty()),
        Err(e) => assert_eq!(e.code(), ErrorCode::Unsupported, "{e}"),
    }
    c.close().await;
    c.close().await;
}

#[test]
fn blocking_round_trip() {
    load_bootstrap_env();
    let c = BlockingClient::from_env().expect("client");
    assert!(c.health().expect("health").healthy);
    c.ping().expect("ping");
    c.close();
}

#[tokio::test]
async fn conformance() {
    load_bootstrap_env();
    #[allow(unused_mut)]
    let mut runner = ConformanceRunner::new(conformance_dir())
        // Declare what the service supports; justify every skip in docs/compatibility.md.
        .capabilities(["version", "write", "delete", "versions", "query"])
        .handler(CoreHandler::new(Client::from_env));
    // @sdk-kit:if secrets
    if let Some(provider) = secrets_provider(&client()) {
        let handler = sdk::testing::SecretsHandler::new(move || provider.clone());
        runner = runner.handler(handler);
    }
    // @sdk-kit:endif
    let report = runner.run().await.expect("scenarios load");
    println!("{report}");
    report.assert_success();
}
// @sdk-kit:if secrets

/// The service's `SecretsProvider` for the `secrets` scenarios. Return it once the service
/// module exists (e.g. `Some(Arc::new(client.kv()))`); `None` leaves them unregistered.
fn secrets_provider(_client: &Client) -> Option<std::sync::Arc<dyn sdk::secrets::SecretsProvider>> {
    None
}
// @sdk-kit:endif
