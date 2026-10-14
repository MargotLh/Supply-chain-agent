# Order System API (Mule 4)

A real MuleSoft implementation of the integration layer. It implements the same contract as the Python stand-in (`integration/api.py`, `integration/order-system-api.raml`), so the agents can use either one by changing `INTEGRATION_URL`.

```text
Agent → ToolGateway → tool → Mule app (this folder) → legacy ERP (mock_erp/)
```

## What's inside

| File | Role |
|---|---|
| `src/main/mule/global.xml` | HTTP listener (port 8081) and ERP requester, properties, policies (client-id enforcement, correlation ID, logging), error handling |
| `src/main/mule/system-api.xml` | System API: one flow per ERP resource (orders, shipments, inventory, suppliers, order actions, notifications) |
| `src/main/mule/process-api.xml` | Process API: `/process/orders/{id}/context` composes the order and shipment lookups |
| `src/main/mule/event-api.xml` | Event API: exposes the ERP outbox as canonical `ORDER_DELAYED` events |
| `src/main/resources/modules/Canonical.dwl` | DataWeave module: every SAP-style ↔ canonical mapping (`MATNR` → `sku`, `WERKS` → `warehouse_id`, ...) |
| `src/main/resources/config.yaml` | Default properties: ports, ERP location, client credentials |
| `pom.xml`, `mule-artifact.json` | Maven build and Mule app descriptor |
| `Dockerfile` | Builds the app and runs it on the free Mule runtime (Community Edition) |

Every flow does the same three things: apply the policies, call the ERP, map the answer with `Canonical.dwl`. Errors come back as `{"detail": ...}` with the same status codes as the Python stand-in (401 without credentials, 404 for unknown orders).

The mappings use `set-payload` with a DataWeave module rather than the *Transform Message* component (`ee:transform`). That is because *Transform Message* only exists in the Enterprise runtime; this way the app also runs on the free Community runtime.

## Run it

### Option 1: Docker (no MuleSoft account needed)

```bash
INTEGRATION_URL=http://mulesoft:8081 docker compose --profile mulesoft up --build
```

This starts the mock ERP, the Mule app and the orchestrator, with the orchestrator using Mule instead of the Python stand-in. Mule takes about 40 seconds to start; until then the orchestrator logs `poll failed`, then carries on by itself. Then use the same `curl` commands as in the main README.

To run the CLI demo through Mule instead:

```bash
uvicorn mock_erp.api:app --host 0.0.0.0 --port 8001          # terminal 1
docker build -t order-system-api mulesoft/                    # terminal 2
docker run --rm -p 8081:8081 order-system-api \
  /opt/mule/bin/mule -M-Derp.host=host.docker.internal -M-Derp.port=8001
INTEGRATION_URL=http://localhost:8081 ERP_URL=http://localhost:8001 \
  python run_demo.py --scenario all --decision approve        # terminal 3
```

With `INTEGRATION_URL` set, the demo doesn't reset the ERP between runs. Restart the ERP or run `curl -X POST localhost:8001/erp/_reset` first.

### Option 2: Anypoint Code Builder (MuleSoft's VS Code editor)

1. Install the *Anypoint Extension Pack* in VS Code and sign in with an Anypoint Platform account (the free trial works).
2. Open the `mulesoft/order-system-api` folder. You can view each flow as a diagram.
3. Start the ERP: `uvicorn mock_erp.api:app --port 8001`.
4. Run the app from Code Builder (Run → Start Debugging). It listens on `localhost:8081`.
5. Run the demo with `INTEGRATION_URL=http://localhost:8081 ERP_URL=http://localhost:8001`.

### Option 3: CloudHub (MuleSoft's cloud)

1. Build the app: `mvn clean package` → `target/order-system-api-1.0.0-mule-application.jar`.
2. In Anypoint Platform, go to **Runtime Manager → Deploy Application** and upload the jar.
3. CloudHub can't reach `localhost`, so the ERP has to be reachable from the internet (for example through a tunnel such as `ngrok http 8001`). Set `erp.protocol`, `erp.host` and `erp.port` in the app's **Properties** tab.
4. Point the agents at the app's public URL: `INTEGRATION_URL=https://<your-app-url>`.

On Anypoint Platform you would normally also publish `order-system-api.raml` to Exchange and apply *Client ID Enforcement* in API Manager. That policy would replace the check in `apply-policies`.

## Build without Docker

Needs Java 17 and Maven 3.9+:

```bash
cd mulesoft/order-system-api
mvn clean package
```
