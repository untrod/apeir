# Quick Start

```console
python -m pip install "nous-runtime[ui]==0.1.0a0"
mkdir nous-example
cd nous-example
nous project init
nous
```

Inside the terminal:

```text
/help
/provider add
/status
/dashboard
```

## Configure a Provider

`/provider add` opens a service-first Wizard. Choose a recognizable service such as OpenAI, DeepSeek, Claude, Ollama, OpenRouter, SiliconFlow, Moonshot AI, or Azure OpenAI. Generic OpenAI-compatible, Local HTTP, and Custom Provider entries remain available for advanced configurations.

The Wizard maps the selected service to the existing Provider protocol, proposes the service endpoint and environment-variable name, discovers available models when the service permits it, and lets you map the selected model to existing capabilities. Endpoint defaults are editable.

Authentication options are:

- environment-variable reference (recommended);
- local operating-system secret storage;
- a process-scoped key used only by the current Runtime process;
- no credential for local services that do not require one.

Secrets are not written to `providers.json`. Use `/provider quick` for a short service-and-key setup. A key entered by the quick flow is process-scoped and must be configured again after Runtime restart or replaced with an environment-variable or local secret-store reference.

Use these commands to inspect the result:

```text
/provider list
/provider doctor
/provider doctor deepseek
/provider test deepseek
/provider ping deepseek
```

Provider Doctor reports endpoint configuration, credential availability, authentication result, selected-model discovery, protocol streaming support, and measured probe latency. It states when streaming was not exercised rather than treating protocol support as a completed streaming test.

For Server clients, set `NOUS_API_TOKEN`, start the local Server, then configure the same token in VS Code SecretStorage, the Desktop connection screen, or an SDK client. Runs, events, conversations and approvals remain owned by the Server Runtime.