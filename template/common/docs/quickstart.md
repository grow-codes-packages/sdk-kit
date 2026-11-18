# Quickstart

Connect to __DISPLAY__, check that it is healthy, make an authenticated call and close the client.
The client reads `GROW___KEY_UPPER___URL` and `GROW___KEY_UPPER___TOKEN` (and the vendor variables
listed in [Configuration](configuration.md)), or takes the values in code.

```sh
export GROW___KEY_UPPER___URL=http://127.0.0.1:__PORT__
export GROW___KEY_UPPER___TOKEN=...   # never commit real tokens
```

=== "TypeScript"

    ```ts
    import { __SERVICE__Client } from "@grow-codes/__KEY__";

    const client = __SERVICE__Client.fromEnv();
    try {
      const health = await client.health();
      console.log("healthy:", health.healthy, health.status);
      console.log("ping:", await client.ping(), "ms");
      console.log("server version:", await client.serverVersion());
    } finally {
      await client.close();
    }
    ```

=== "Rust"

    ```rust
    use grow___KEY_SNAKE__::__SERVICE__Client;

    #[tokio::main]
    async fn main() -> grow___KEY_SNAKE__::Result<()> {
        let client = __SERVICE__Client::from_env()?;
        let health = client.health().await?;
        println!("healthy: {} {}", health.healthy, health.status);
        println!("ping: {:?}", client.ping().await?);
        println!("server version: {}", client.server_version().await?);
        client.close().await;
        Ok(())
    }
    ```

=== "Go"

    ```go
    package main

    import (
        "context"
        "fmt"
        "log"

        __PKG__ "github.com/grow-codes-packages/__KEY__/go"
    )

    func main() {
        ctx := context.Background()
        client, err := __PKG__.NewClientFromEnv()
        if err != nil {
            log.Fatal(err)
        }
        defer client.Close()

        health, err := client.Health(ctx)
        if err != nil {
            log.Fatal(err)
        }
        fmt.Println("healthy:", health.Healthy, health.Status)

        latency, err := client.Ping(ctx)
        if err != nil {
            log.Fatal(err)
        }
        fmt.Println("ping:", latency)

        version, err := client.ServerVersion(ctx)
        if err != nil {
            log.Fatal(err)
        }
        fmt.Println("server version:", version)
    }
    ```

=== "Python"

    ```python
    from grow___KEY_SNAKE__ import __SERVICE__Client

    with __SERVICE__Client.from_env() as client:
        health = client.health()
        print("healthy:", health.healthy, health.status)
        print("ping:", client.ping(), "ms")
        print("server version:", client.server_version())
    ```

    Async code uses `Async__SERVICE__Client` with the same methods:

    ```python
    import asyncio
    from grow___KEY_SNAKE__ import Async__SERVICE__Client

    async def main() -> None:
        async with Async__SERVICE__Client.from_env() as client:
            print(await client.health())

    asyncio.run(main())
    ```

=== "Java"

    ```java
    import codes.grow.packages.__PKG__.__SERVICE__Client;
    import codes.grow.packages.__PKG__.core.HealthStatus;

    public final class Quickstart {
      public static void main(String[] args) {
        try (__SERVICE__Client client = __SERVICE__Client.fromEnv()) {
          HealthStatus health = client.health();
          System.out.println("healthy: " + health.healthy() + " " + health.status());
          System.out.println("ping: " + client.ping().toMillis() + " ms");
          System.out.println("server version: " + client.serverVersion());
        }
      }
    }
    ```

## Next steps

- [Configuration](configuration.md): timeouts, retries, TLS, proxy, environment variables.
- [Functions](functions.md): the __DISPLAY__ API of this SDK.
- [Error handling](errors.md): error codes and retries.
