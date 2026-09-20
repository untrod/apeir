# @nous-runtime/sdk

TypeScript and JavaScript client for an authoritative Nous Server Runtime.

```ts
import { NousClient } from "@nous-runtime/sdk";

const runtime = new NousClient({
  baseUrl: "http://localhost:8770",
  token: process.env.NOUS_API_TOKEN,
});
const result = await runtime.workflow("example.workflow", { message: "Hello" });
```

The client keeps no authoritative Runtime state. Authentication uses a Bearer token header. Run-event replay uses a resumable sequence cursor over the Runtime HTTP API; call `close()` on the returned subscription during cleanup.