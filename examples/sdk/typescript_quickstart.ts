import { NousClient } from "../../nous_runtime/sdk/client";

const runtime = new NousClient({ token: process.env.NOUS_API_TOKEN ?? "" });
runtime.workflow("example.workflow", { message: "Hello, Nous" }).then(console.log);