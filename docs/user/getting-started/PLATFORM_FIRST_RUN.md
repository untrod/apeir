# First Run Guide

Welcome to Nous Runtime! This guide walks you through your first experience.

## 1. Environment Check

```bash
nous doctor
```

This checks your OS, Python, memory, disk, network, and dependencies.

Everything green? You're ready.

## 2. Initialize

```bash
nous init
```

The interactive wizard will:
1. Create your workspace
2. Help you choose a mode (Personal/Developer/Server/Edge)
3. Configure an AI provider (optional)
4. Install starter packs (optional)

## 3. Configure a Provider

```bash
nous provider add
```

Choose from OpenAI, DeepSeek, Claude, Ollama, or custom.

Or set environment variables:
```bash
export NOUS_LLM_API_KEY="sk-..."
export NOUS_LLM_API_URL="https://api.deepseek.com/v1/chat/completions"
export NOUS_LLM_MODEL="deepseek-chat"
```

## 4. Start

```bash
nous start
```

## 5. Interactive Shell

```bash
nous
```

Type natural language or slash commands:
```
❯ /status
❯ /providers
❯ analyze this project
❯ check system health
```

## 6. Run the Demo

```bash
nous demo
```

This shows the full Goal -> Plan -> Execute -> Audit pipeline.

## 7. Install a Pack

```bash
nous pack install packs/examples/hello_pack
nous capability run hello.hello
```

## 8. Create Your Own Pack

```bash
nous dev new pack my-pack
cd my-pack
nous dev validate
nous pack install .
```

## Next Steps

- Read the User Guide: `docs/user/guides/USER_GUIDE.md`
- CLI Reference: `docs/user/guides/CLI_GUIDE.md`
- Pack Development: `docs/user/guides/PACK_GUIDE.md`
- Architecture: `docs/user/guides/ARCHITECTURE_OVERVIEW.md`
