# Simon Casino Resort — AI Campaign Manager

A multi-agent AI marketing campaign assistant using A2A protocol, MCP tools, and LLM inference on Red Hat OpenShift AI.

## Architecture

```mermaid
flowchart TD
    subgraph ui [User Interface]
        Frontend["React Dashboard\n(nginx :8080)"]
    end

    subgraph api [API Layer]
        CampaignAPI["Campaign API\n(Flask :5000)"]
        EventHub["Event Hub\n(SSE :5001)"]
    end

    subgraph agents [A2A Agents]
        Director["Campaign Director\n(LangGraph :8080)"]
        CP["Creative Producer\n(:8081)"]
        CA["Customer Analyst\n(:8082)"]
        DM["Delivery Manager\n(:8083)"]
    end

    subgraph mcp [MCP Servers]
        MongoMCP["MongoDB MCP\n(:8090 /mcp)"]
        ImageMCP["ImageGen MCP\n(:8091 /mcp)"]
    end

    subgraph models [GPU Models]
        Coder["Qwen2.5-Coder-32B\n(L40S #1)"]
        Lang["Qwen3-32B\n(L40S #2)"]
        Flux["FLUX.2-klein-4B\n(L40S #3)"]
    end

    Frontend -->|"/api"| CampaignAPI
    Frontend -->|"/events"| EventHub
    CampaignAPI -->|A2A| Director
    Director -->|A2A| CP
    Director -->|A2A| CA
    Director -->|A2A| DM
    CP -->|MCP| ImageMCP
    CP -->|LLM| Coder
    CA -->|"LLM tool calling"| Lang
    CA -->|MCP| MongoMCP
    DM -->|LLM| Lang
    ImageMCP --> Flux
    MongoMCP --> DB[(MongoDB)]
```

## Components

| Component | Port | Purpose |
|-----------|------|---------|
| React Dashboard | 8080 | Campaign portal UI (nginx) |
| Campaign API | 5000 | REST gateway + A2A client |
| Event Hub | 5001 | Real-time SSE agent status |
| Campaign Director | 8080 | LangGraph workflow orchestrator |
| Creative Producer | 8081 | AI image + HTML landing page generation |
| Customer Analyst | 8082 | LLM-driven customer retrieval via MCP |
| Delivery Manager | 8083 | Email generation + K8s deployment |
| MongoDB MCP | 8090 | Customer database tools (streamable-http) |
| ImageGen MCP | 8091 | AI image generation + serving (hybrid MCP) |
| MongoDB | 27017 | Customer/prospect database |

## Quick Start

### Local Development

```bash
cp .env.example .env
# Edit .env with your model endpoints and tokens

docker-compose up
```

Access: http://localhost:3000

### OpenShift Deployment (Kustomize)

```bash
# 1. Copy and edit the overlay secret with your model tokens
cp k8s/overlays/dev/secret.yaml k8s/overlays/dev/secret-local.yaml
# Edit secret-local.yaml with your actual endpoints and tokens

# 2. Deploy everything in one command
oc apply -k k8s/overlays/dev

# 3. Seed MongoDB with customer data
oc exec deployment/mongodb-mcp -- env MONGODB_URI=mongodb://mongodb:27017 python3 seed_data.py

# 4. Import vLLM-Omni ServingRuntime (for image generation)
oc apply -f k8s/imagegen/serving-runtime.yaml
```

**For a different cluster:** Copy `k8s/overlays/dev/` to `k8s/overlays/<your-name>/`, edit `configmap-patch.yaml` (cluster domain, namespaces) and `secret.yaml` (model endpoints, tokens).

## Workflow

1. **Create Campaign** — Define name, description, hotel, audience, dates
2. **Select Theme** — Choose visual style (Luxury Gold, Festive Red, Modern Black, Classic Casino)
3. **Generate Landing Page** — AI generates hero image (FLUX.2) + HTML/CSS (Qwen Coder)
4. **Preview** — Review landing page, regenerate for different layouts
5. **Prepare Emails** — LLM selects MCP tool for customer retrieval, generates email content (EN + ZH)
6. **Go Live** — Deploy to production + send emails

## Technology Stack

- **Frontend**: React 18, TypeScript, Headless UI, Heroicons
- **API Gateway**: Flask 3.0, Flask-CORS
- **Agent Protocol**: A2A SDK 0.3.25 (JSON-RPC 2.0, `a2a-sdk[http-server]`)
- **MCP Transport**: FastMCP 2.12+ (streamable-http at `/mcp`)
- **Orchestration**: LangGraph 0.2+, LangChain 0.2+
- **LLM Inference**: vLLM on RHOAI (Qwen2.5-Coder-32B, Qwen3-32B)
- **Image Generation**: vLLM-Omni 0.18.0 (FLUX.2-klein-4B)
- **Database**: MongoDB 7
- **Platform**: Red Hat OpenShift AI 3.3, 3x NVIDIA L40S GPUs

## Models

| Model | GPU | Purpose | HuggingFace |
|-------|-----|---------|-------------|
| Qwen2.5-Coder-32B-Instruct-FP8 | L40S #1 | HTML/CSS/JS generation | [neuralmagic/Qwen2.5-Coder-32B-Instruct-FP8](https://huggingface.co/neuralmagic/Qwen2.5-Coder-32B-Instruct-FP8) |
| Qwen3-32B-FP8-Dynamic | L40S #2 | Email gen, tool calling, policy validation | [RedHatAI/Qwen3-32B-FP8-dynamic](https://huggingface.co/RedHatAI/Qwen3-32B-FP8-dynamic) |
| FLUX.2-klein-4B | L40S #3 | AI hero image generation (vLLM-Omni) | [black-forest-labs/FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) |
| Granite Guardian HAP 125M | CPU | Hate/abuse/profanity detection (TrustyAI) | [ibm-granite/granite-guardian-hap-125m](https://huggingface.co/ibm-granite/granite-guardian-hap-125m) |
| DeBERTa v3 Prompt Injection v2 | CPU | Prompt injection detection (TrustyAI) | [protectai/deberta-v3-base-prompt-injection-v2](https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2) |

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — Detailed architecture, data flows, sequence diagrams
