import { NousClient } from "../../nous_runtime/sdk/client";

const runtime = new NousClient({ token: process.env.NOUS_API_TOKEN ?? "" });
void runtime.workflow("example.workflow", { message: "Hello, Nous" })
  .then(console.log)
  .catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : "Workflow request failed");
    process.exitCode = 2;
  });
