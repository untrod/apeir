# Models and Providers

Configure a cloud API or local inference service, then select it in Studio.
本地模型和云端 API 可以同时配置；配置成功、服务健康与推理成功分别检查。

## Configure

Open **Models** in Studio. Add a Provider with its supported protocol, endpoint,
exact vendor model ID and credential reference. Save, select a registered model,
then choose **Test** only when you intend to make a model request.

Browser Studio does not save raw API keys. Local native
**Settings → Credentials** uses the existing system store. Configuration retains
reference names, not secret values. Never paste a key into layout JSON, a
screenshot or an issue.

The CLI uses the same saved configuration:

```bash
apeir provider add
apeir provider list
apeir provider show PROVIDER_ID
apeir provider status
apeir provider doctor
```

Replace `PROVIDER_ID` with the saved identity. `apeir provider quick` is the
existing guided shortcut with process-scoped credentials; do not assume those
credentials will survive a process restart.

## Cloud and local services

| Service | Requirement |
| --- | --- |
| OpenAI-compatible cloud API | Exact supported endpoint, model ID and valid credential reference |
| Compatible DeepSeek endpoint | Verify the actual API and requested parameters; the name alone proves nothing |
| Ollama / llama.cpp / vLLM server | Start the supported local service separately and select its actual protocol/model |
| Anthropic Messages | Production calls are BLOCKED: the frozen NKI Worker has no Messages backend |
| Claude behind a compatible proxy | Only a genuinely implemented OpenAI-compatible proxy can use that adapter |

Provider-scoped Gateway IDs keep identical vendor IDs separate: for example,
`cloud/vendor/model` and `workstation/vendor/model`. The backend still receives
its original vendor ID. After upgrading an older slash-containing unscoped ID,
reselect it from the current catalog; ambiguous identities are not redirected.

Automatic local detection accepts exact loopback hosts. A Provider called
“local”, or a URL containing that word, does not establish locality. A trusted
remote inference node requires an explicit host locality declaration.
PRIVATE/OFFLINE routing does not silently fall back to cloud services.

An installed model file does not start an inference server. Tool calling,
vision, context limits and reasoning parameters need actual endpoint support.

## Test deliberately

```bash
apeir provider ping PROVIDER_ID --json
```

This checks endpoint reachability. It is not proof of authenticated inference.

```bash
apeir provider test PROVIDER_ID --json
```

This sends a minimal model request and can incur cost. Inspect its original
request and usage. Production requests require the configured Gateway and
authenticated Kernel; there is no direct SDK fallback. A process started with
`--no-intelligence` cannot infer even after a profile is saved.

| State | Meaning |
| --- | --- |
| UNCONFIGURED | Required configuration or credential reference is missing |
| BLOCKED | A required execution boundary, protocol or permission is unavailable |
| Endpoint reachable | Network check passed; the model has not necessarily run |
| Model completed | Original inference completed; inspect its response and usage |
| UNKNOWN usage/cost | Not measured, not zero and not free |

After a timeout or lost response, inspect the original request before another
potentially billed call. Changing or deleting a Provider does not cancel a call
already admitted, and deleting a profile does not delete its separate credential.

## See also

- [Studio setup and model tests](../../development/DEVELOPER_PLATFORM.md#first-use-configuration-and-model-tests)
- [Recorded activity and streaming limits](../../development/DEVELOPER_PLATFORM.md#watching-a-request)
- [Context, Tokens and cost](../../development/DEVELOPER_PLATFORM.md#model-usage-and-cost)
- [Provider development](../../development/PROVIDER_DEVELOPMENT.md)

`nous provider` remains a compatibility alias for `apeir provider`.
