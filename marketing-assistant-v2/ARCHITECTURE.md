# Architecture Document
# Marketing Campaign Assistant v2 — Microservices Architecture

**Version:** 2.2  
**Last Updated:** March 31, 2026  
**Platform:** Red Hat OpenShift AI 3.3

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Service Inventory](#2-service-inventory)
3. [High-Level Architecture](#3-high-level-architecture)
4. [Data Flow: Campaign Lifecycle](#4-data-flow-campaign-lifecycle)
5. [A2A Protocol Flow](#5-a2a-protocol-flow)
6. [MCP Protocol Flow](#6-mcp-protocol-flow)
7. [LangGraph Workflows](#7-langgraph-workflows)
8. [SSE Event System](#8-sse-event-system)
9. [Kubernetes Deployment Flow](#9-kubernetes-deployment-flow)
10. [Frontend Architecture](#10-frontend-architecture)
11. [GPU & Model Assignment](#11-gpu--model-assignment)
12. [Detailed Service Reference](#12-detailed-service-reference)

---

## 1. System Overview

The Marketing Campaign Assistant is a multi-agent AI system that generates luxury marketing campaigns for Macau casinos. It uses four protocols:

| Protocol | Purpose | Implementation |
|----------|---------|----------------|
| **A2A** (Agent-to-Agent) | Inter-agent communication | `a2a-sdk` JSON-RPC 2.0 over HTTP |
| **MCP** (Model Context Protocol) | Tool access (database, image gen) | FastMCP streamable-http transport |
| **OpenAI API** | LLM inference (Qwen models) | vLLM-compatible `/v1/chat/completions` |
| **SSE** (Server-Sent Events) | Real-time UI updates | Flask-based Event Hub |

---

## 2. Service Inventory

| Service | Port | Technology | Role |
|---------|------|------------|------|
| **Frontend** | 8080 (nginx) | React 18, TypeScript, nginx | Static SPA + API/SSE proxy |
| **Campaign API** | 5000 | Flask, Flask-CORS | REST gateway, A2A client to Director |
| **Event Hub** | 5001 | Flask | SSE pub/sub for real-time agent status |
| **Campaign Director** | 8080 | a2a-sdk, LangGraph, Starlette | Orchestrator, workflow coordination |
| **Creative Producer** | 8081 | a2a-sdk, FastMCP Client | HTML/CSS landing page generation |
| **Customer Analyst** | 8082 | a2a-sdk, FastMCP Client, Qwen3 | LLM-driven customer retrieval via MCP |
| **Delivery Manager** | 8083 | a2a-sdk, Kubernetes client | Email generation + K8s deployment |
| **MongoDB MCP** | 8090 | FastMCP streamable-http | Customer database tools |
| **ImageGen MCP** | 8091 | FastMCP hybrid + Starlette | AI image generation + serving |
| **MongoDB** | 27017 | mongo:7 | Customer/prospect database |
| **vLLM (Qwen Coder)** | KServe | vLLM, L40S #1 | HTML code generation |
| **vLLM (Qwen3)** | KServe | vLLM, L40S #2 | Email gen + tool calling |
| **vLLM-Omni (FLUX.2)** | KServe | vLLM-Omni 0.18.0, L40S #3 | Image generation |

---

## 3. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                BROWSER                                            │
│                          React SPA (static)                                       │
└────────────────────┬─────────────────────────────┬───────────────────────────────┘
                     │ /api/*                       │ /events/*
                     ▼                              ▼
┌──────────────────────────────────┐  ┌──────────────────────────────┐
│         Campaign API             │  │         Event Hub             │
│       (Flask, port 5000)         │  │    (Flask SSE, port 5001)     │
│                                  │  │                               │
│  A2A Client → Director           │  │  POST /events/{id}/publish    │
│  REST proxy → /campaigns         │  │  GET  /events/{id} (SSE)      │
└──────────────┬───────────────────┘  └───────────────────────────────┘
               │ A2A (JSON-RPC 2.0)           ▲ SSE publish
               ▼                              │ (from all agents)
┌──────────────────────────────────────────────────────────────────────┐
│                    Campaign Director (port 8080)                      │
│              A2A Server + LangGraph Orchestrator                      │
│                                                                       │
│  Skills: create_campaign, generate_landing_page,                      │
│          prepare_email_preview, go_live                                │
│                                                                       │
│  3 LangGraph Workflows:                                               │
│    Landing:  generate_landing_page → deploy_preview                   │
│    Email:    retrieve_customers → generate_email                      │
│    GoLive:   deploy_production → send_emails                          │
└──────┬────────────────┬────────────────────┬─────────────────────────┘
       │ A2A            │ A2A                │ A2A
       ▼                ▼                    ▼
┌──────────────┐ ┌──────────────┐ ┌───────────────────┐
│  Creative    │ │  Customer    │ │  Delivery          │
│  Producer    │ │  Analyst     │ │  Manager           │
│  (8081)      │ │  (8082)      │ │  (8083)            │
│              │ │              │ │                     │
│  1 skill     │ │  1 skill     │ │  4 skills           │
└──────┬───────┘ └──────┬───────┘ └──────┬──────────────┘
       │ MCP            │ MCP + LLM       │ LLM + K8s API
       ▼                ▼                 ▼
┌──────────────┐ ┌──────────────┐ ┌───────────────────┐
│  ImageGen    │ │  MongoDB     │ │  Qwen3-32B        │
│  MCP (8091)  │ │  MCP (8090)  │ │  (vLLM, L40S #2)  │
│  /mcp        │ │  /mcp        │ │                     │
│  /images/*   │ │              │ │  + OpenShift K8s    │
└──────┬───────┘ └──────┬───────┘ │  API (deploy)       │
       │                │         └─────────────────────┘
       ▼                ▼
┌──────────────┐ ┌──────────────┐
│  FLUX.2      │ │  MongoDB     │
│  klein-4B    │ │  (mongo:7)   │
│  (L40S #3)   │ │  casino_crm  │
└──────────────┘ └──────────────┘
```

---

## 4. Data Flow: Campaign Lifecycle

### Step-by-Step Flow

```
USER creates campaign in browser

  ┌─── Step 0: Define Campaign Identity (frontend only, no API) ──┐
  │  Form: name, description, hotel, audience, dates               │
  └───────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌─── Step 1: Theme Selection + Generate ────────────────────────┐
  │  Browser: POST /api/campaigns (create)                         │
  │  Browser: POST /api/campaigns/{id}/generate                    │
  │                                                                │
  │  Campaign API → A2A → Director.create_campaign                 │
  │  Campaign API → A2A → Director.generate_landing_page           │
  │                                                                │
  │  Director (LangGraph landing workflow):                        │
  │    1. generate_landing_page_node                               │
  │       → A2A → Creative Producer                                │
  │         → MCP → ImageGen MCP → FLUX.2 (generate hero image)   │
  │         → Qwen Coder (generate HTML with image placeholder)    │
  │         → Replace placeholder with public image URL            │
  │    2. deploy_preview_node                                      │
  │       → A2A → Delivery Manager                                 │
  │         → K8s API: ConfigMap + Deployment + Service + Route    │
  │         → Returns preview URL                                  │
  │                                                                │
  │  Status: generating → preview_ready                            │
  └───────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌─── Step 2: Preview Landing Page ──────────────────────────────┐
  │  Browser shows preview URL + QR code                           │
  │  User can click "Regenerate" for a different layout            │
  └───────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌─── Step 3: Prepare Emails ────────────────────────────────────┐
  │  Browser: POST /api/campaigns/{id}/preview-email               │
  │                                                                │
  │  Director (LangGraph email workflow):                          │
  │    1. retrieve_customers_node                                  │
  │       → A2A → Customer Analyst                                 │
  │         → Qwen3 LLM (tool selection with function calling)     │
  │         → MCP → MongoDB MCP → MongoDB (real query)             │
  │    2. generate_email_node                                      │
  │       → A2A → Delivery Manager                                 │
  │         → Qwen3 LLM (email content EN + ZH, streaming)        │
  │                                                                │
  │  Status: email_ready                                           │
  └───────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌─── Step 4: Confirmation + Go Live ────────────────────────────┐
  │  Browser: POST /api/campaigns/{id}/approve                     │
  │                                                                │
  │  Director (LangGraph go-live workflow):                        │
  │    1. deploy_production_node                                   │
  │       → A2A → Delivery Manager → K8s API (prod namespace)     │
  │    2. send_emails_node                                         │
  │       → A2A → Delivery Manager (simulated send)               │
  │                                                                │
  │  Status: live                                                  │
  └───────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌─── Step 5: Success ───────────────────────────────────────────┐
  │  Browser shows production URL, QR code, recipient count        │
  └───────────────────────────────────────────────────────────────┘
```

---

## 5. A2A Protocol Flow

### 3-Layer Agent Pattern

Every A2A agent follows this structure:

```
__main__.py                    agent_executor.py              agent.py
┌─────────────────────┐       ┌─────────────────────┐       ┌─────────────────────┐
│ AgentCard            │       │ AgentExecutor        │       │ Pure Business Logic  │
│ A2AStarletteApp      │──────▶│ execute()            │──────▶│ skill methods         │
│ Uvicorn server       │       │ JSON parse → dispatch│       │ LLM calls, MCP calls │
│ Health check route   │       │ Artifact → response  │       │ Event publishing      │
└─────────────────────┘       └─────────────────────┘       └─────────────────────┘
```

### Message Format

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "{\"skill\": \"generate_landing_page\", \"campaign_id\": \"abc123\", ...}"}],
      "messageId": "hex-uuid"
    }
  },
  "id": "request-uuid"
}
```

### Call Chain

```
Campaign API                    Campaign Director              Downstream Agent
     │                               │                              │
     │  A2AClient.send_message()     │                              │
     │  ─────────────────────────▶   │                              │
     │  POST / (JSON-RPC 2.0)       │                              │
     │                               │  CampaignDirectorExecutor    │
     │                               │  .execute()                  │
     │                               │  → handle_skill(skill, params) │
     │                               │  → LangGraph workflow        │
     │                               │                              │
     │                               │  call_a2a_agent(url, skill)  │
     │                               │  ─────────────────────────▶  │
     │                               │  POST / (JSON-RPC 2.0)      │
     │                               │                              │  AgentExecutor
     │                               │                              │  .execute()
     │                               │                              │  → business logic
     │                               │  ◀─────────────────────────  │
     │                               │  artifact: JSON result       │
     │  ◀─────────────────────────   │                              │
     │  artifact: JSON result        │                              │
```

---

## 6. MCP Protocol Flow

### Transport: Streamable-HTTP

Both MCP servers use FastMCP's `streamable-http` transport, which serves the MCP protocol at `/mcp`:

```
Customer Analyst                    MongoDB MCP Server
     │                                   │
     │  FastMCP Client                   │
     │  Client("http://mongodb-mcp:8090/mcp") │
     │  ─────────────────────────────▶   │
     │  POST /mcp (JSON-RPC: initialize) │
     │  ◀─────────────────────────────   │
     │  capabilities, tools              │
     │                                   │
     │  call_tool("get_customers_by_tier", │
     │            {"tier": "platinum"})   │
     │  ─────────────────────────────▶   │
     │  POST /mcp (JSON-RPC: tools/call) │
     │                                   │  → PyMongo query
     │                                   │  → MongoDB (casino_crm)
     │  ◀─────────────────────────────   │
     │  result: [{customer_id, name...}] │
```

### Customer Analyst: LLM-Driven Tool Selection

```
Customer Analyst                  Qwen3 LLM                   MongoDB MCP
     │                               │                              │
     │  "Retrieve Platinum members"  │                              │
     │  + tool definitions           │                              │
     │  ─────────────────────────▶   │                              │
     │  POST /v1/chat/completions    │                              │
     │  (streaming, tools=[...])     │                              │
     │                               │                              │
     │  ◀─────────────────────────   │                              │
     │  tool_call: get_customers_by_tier │                          │
     │  args: {"tier": "platinum"}   │                              │
     │                               │                              │
     │  FastMCP Client.call_tool()   │                              │
     │  ─────────────────────────────────────────────────────────▶  │
     │                               │                              │  → MongoDB query
     │  ◀─────────────────────────────────────────────────────────  │
     │  [VIP-001, VIP-002, VIP-004, VIP-006]                       │
```

### ImageGen MCP: Hybrid Architecture

```
Creative Producer                 ImageGen MCP Server           FLUX.2 Model
     │                                   │                          │
     │  FastMCP Client                   │                          │
     │  Client("http://imagegen-mcp:8091/mcp") │                   │
     │  call_tool("generate_campaign_image") │                     │
     │  ─────────────────────────────▶   │                          │
     │  POST /mcp (MCP protocol)         │                          │
     │                                   │  POST /v1/images/generations
     │                                   │  ────────────────────▶   │
     │                                   │                          │  FLUX.2
     │                                   │  ◀────────────────────   │  diffusion
     │                                   │  base64 PNG              │
     │                                   │                          │
     │                                   │  Store in memory         │
     │  ◀─────────────────────────────   │  (image_store[id])       │
     │  {image_url: "https://...         │                          │
     │   /images/img-xxx.png"}           │                          │
     │                                   │                          │
BROWSER ─── GET /images/img-xxx.png ────▶│                          │
     │  ◀─────────────────────────────   │                          │
     │  PNG bytes (via public Route)     │                          │
```

---

## 7. LangGraph Workflows

The Campaign Director orchestrates three sequential workflows using LangGraph `StateGraph`:

### Workflow 1: Landing Page Generation

```
START → generate_landing_page_node ──┬── (failed) ──→ END
                                     │
                                     └── (continue) → deploy_preview_node → END
```

- `generate_landing_page_node`: A2A → Creative Producer → ImageGen MCP (hero image) + Qwen Coder (HTML)
- `deploy_preview_node`: A2A → Delivery Manager → K8s API (ConfigMap + Deployment + Service + Route in dev namespace)

### Workflow 2: Email Preview

```
START → retrieve_customers_node ──┬── (failed) ──→ END
                                  │
                                  └── (continue) → generate_email_node → END
```

- `retrieve_customers_node`: A2A → Customer Analyst → Qwen3 LLM (tool selection) → MCP → MongoDB
- `generate_email_node`: A2A → Delivery Manager → Qwen3 LLM (email content EN + ZH)

### Workflow 3: Go Live

```
START → deploy_production_node ──┬── (failed) ──→ END
                                 │
                                 └── (continue) → send_emails_node → END
```

- `deploy_production_node`: A2A → Delivery Manager → K8s API (prod namespace)
- `send_emails_node`: A2A → Delivery Manager (simulated email send)

### Conditional Edge: `_check_failed`

Each workflow uses `add_conditional_edges` with `_check_failed(state)`:
- Returns `"end"` if `state["status"] == "failed"` → routes to `END`
- Returns `"continue"` otherwise → routes to next node

### State: `CampaignState` (TypedDict)

```python
class CampaignState(TypedDict):
    campaign_id: str
    campaign_name: str
    campaign_description: str
    hotel_name: str
    target_audience: str
    theme: str
    start_date: str
    end_date: str
    status: str
    landing_page_html: str
    preview_url: str
    production_url: str
    email_subject_en: str
    email_body_en: str
    email_subject_zh: str
    email_body_zh: str
    customer_list: List[dict]
    customer_count: int
    error_message: str
    messages: Annotated[list, operator.add]
```

---

## 8. SSE Event System

### Event Hub Architecture

```
Agents (publish)                    Event Hub                   Browser (subscribe)
     │                                   │                          │
     │  POST /events/{id}/publish        │                          │
     │  ─────────────────────────────▶   │                          │
     │  {event_type, agent, task, data}  │                          │
     │                                   │  broadcast_event()       │
     │                                   │  → all queues for {id}   │
     │                                   │                          │
     │                                   │  GET /events/{id} (SSE)  │
     │                                   │  ◀────────────────────   │
     │                                   │  EventSource connection  │
     │                                   │                          │
     │                                   │  data: {event_type,      │
     │                                   │         agent, task}      │
     │                                   │  ─────────────────────▶  │
```

### Event Types

| Event Type | Published By | Meaning |
|------------|-------------|---------|
| `connected` | Event Hub | SSE connection established |
| `campaign_created` | Campaign Director | New campaign created |
| `workflow_status` | Campaign Director, Creative Producer, Customer Analyst | Workflow progress update |
| `agent_started` | All agents | Agent began processing a task |
| `agent_completed` | All agents | Agent finished a task successfully |
| `agent_error` | All agents | Agent encountered an error |

### Event Payload

```json
{
    "campaign_id": "abc123",
    "event_type": "agent_started",
    "agent": "Creative Producer",
    "task": "Generating hero image with AI",
    "data": {},
    "timestamp": "2026-03-31T15:00:00"
}
```

---

## 9. Kubernetes Deployment Flow

When the Delivery Manager deploys a campaign landing page:

```
Delivery Manager
     │
     │  deploy_campaign_to_k8s(campaign_id, html_content, namespace)
     │
     ├── 1. init_k8s_client() (in-cluster or kubeconfig)
     │
     ├── 2. Create/Replace ConfigMap: {deployment}-html
     │       key: "index.html" = campaign HTML content
     │
     ├── 3. Create/Replace ConfigMap: {deployment}-nginx
     │       key: "default.conf" = nginx config (port 8080, SPA)
     │
     ├── 4. Create/Replace Deployment: campaign-{id[:8]}-preview
     │       image: nginxinc/nginx-unprivileged:alpine
     │       mounts: html + nginx ConfigMaps
     │
     ├── 5. Create/Replace Service: campaign-{id[:8]}-preview
     │       port 80 → targetPort 8080
     │
     └── 6. Create/Replace Route (OpenShift)
             host: campaign-{id[:8]}-preview-{namespace}.{CLUSTER_DOMAIN}
             TLS: edge termination
             → Returns: https://campaign-{id[:8]}-preview-{namespace}.{CLUSTER_DOMAIN}/
```

### Namespace Layout

| Namespace | Purpose |
|-----------|---------|
| `marketing-assistant-v2` | All application services (10 pods) |
| `0-marketing-assistant-demo-dev` | Preview campaign deployments |
| `0-marketing-assistant-demo-prod` | Production campaign deployments |
| `0-marketing-assistant-demo` | Model serving (vLLM, vLLM-Omni) |

### RBAC

`k8s/rbac.yaml` grants `edit` role to `system:serviceaccount:marketing-assistant-v2:default` in both dev and prod namespaces.

---

## 10. Frontend Architecture

### Nginx Proxy Configuration

```
Browser
  │
  ├── /              → static React build (build/)
  ├── /api/*         → proxy_pass http://campaign-api:5000
  └── /events/*      → proxy_pass http://event-hub:5001 (buffering off, SSE)
```

### React Routes

| Path | Component | Purpose |
|------|-----------|---------|
| `/` | Dashboard | Campaign list |
| `/campaign/create` | CampaignCreate | New campaign wizard |
| `/campaign/:id` | CampaignCreate | Resume existing campaign |

### Internal Step Machine

| `currentStep` | UI Label | Actions |
|---------------|----------|---------|
| 0 | "Step 1 of 4" | Form validation only |
| 1 | "Step 2 of 4" | Create campaign + generate landing page |
| 2 | Preview | Landing page preview + "Prepare Emails" |
| 3 | Email Preview | Email content + recipients |
| 4 | Confirmation | "Go Live Now" button |
| 5 | Success | Production URLs + QR codes |

### Status-to-Step Mapping (resume flow)

| Backend Status | Frontend Step |
|----------------|---------------|
| `draft`, `generating`, `failed` | 1 |
| `preview_ready` | 2 |
| `email_ready` | 3 |
| `approved`, `deploying` | 4 |
| `live` | 5 |

---

## 11. GPU & Model Assignment

| GPU | Model | Served By | Used By |
|-----|-------|-----------|---------|
| L40S #1 (48GB) | Qwen2.5-Coder-32B-FP8 | vLLM (KServe) | Creative Producer (HTML generation) |
| L40S #2 (48GB) | Qwen3-32B-FP8-Dynamic | vLLM (KServe) | Delivery Manager (email gen), Customer Analyst (tool calling) |
| L40S #3 (48GB) | FLUX.2-klein-4B | vLLM-Omni 0.18.0 (KServe) | ImageGen MCP (hero banner images) |

### Model Endpoints

```
Code Model:  https://qwen25-coder-32b-fp8-0-marketing-assistant-demo.{CLUSTER_DOMAIN}/v1
Lang Model:  https://qwen3-32b-fp8-dynamic-0-marketing-assistant-demo.{CLUSTER_DOMAIN}/v1
Image Model: https://flux2-klein-4b-0-marketing-assistant-demo.{CLUSTER_DOMAIN}/v1
```

All endpoints use kube-rbac-proxy authentication (Bearer token from ServiceAccount).

---

## 12. Detailed Service Reference

### Campaign API

| Route | Method | Handler | Downstream Call |
|-------|--------|---------|-----------------|
| `/health` | GET | `health_check` | — |
| `/api/themes` | GET | `get_themes` | `shared.models.CAMPAIGN_THEMES` |
| `/api/campaigns` | GET | `list_campaigns` | HTTP GET `{DIRECTOR}/campaigns` |
| `/api/campaigns` | POST | `create_campaign` | A2A → Director `create_campaign` |
| `/api/campaigns/<id>` | GET | `get_campaign` | HTTP GET `{DIRECTOR}/campaigns/{id}` |
| `/api/campaigns/<id>/generate` | POST | `generate_landing_page` | A2A → Director `generate_landing_page` |
| `/api/campaigns/<id>/preview-email` | POST | `preview_email` | A2A → Director `prepare_email_preview` |
| `/api/campaigns/<id>/approve` | POST | `approve_campaign` | A2A → Director `go_live` |

### Campaign Director

| Skill | Handler | LangGraph Workflow | Downstream A2A Calls |
|-------|---------|-------------------|---------------------|
| `create_campaign` | `_create_campaign` | — | — |
| `generate_landing_page` | `_generate_landing_page` | Landing workflow | Creative Producer → Delivery Manager |
| `prepare_email_preview` | `_prepare_email_preview` | Email workflow | Customer Analyst → Delivery Manager |
| `go_live` | `_go_live` | Go-live workflow | Delivery Manager (×2) |

### Creative Producer

| Skill | Handler | External Calls |
|-------|---------|----------------|
| `generate_landing_page` | `CreativeProducerAgent.generate()` | MCP → ImageGen MCP (`generate_campaign_image`), LLM → Qwen Coder (`/v1/chat/completions`, streaming) |

### Customer Analyst

| Skill | Handler | External Calls |
|-------|---------|----------------|
| `get_target_customers` | `CustomerAnalystAgent.get_customers()` | LLM → Qwen3 (tool calling, streaming), MCP → MongoDB MCP (tool execution) |

### Delivery Manager

| Skill | Handler | External Calls |
|-------|---------|----------------|
| `generate_email` | `DeliveryManagerAgent.generate_email()` | LLM → Qwen3 (`/v1/chat/completions`, streaming) |
| `deploy_preview` | `DeliveryManagerAgent.deploy_preview()` | K8s API (ConfigMap, Deployment, Service, Route) |
| `deploy_production` | `DeliveryManagerAgent.deploy_production()` | K8s API (prod namespace) |
| `send_emails` | `DeliveryManagerAgent.send_emails()` | Simulated (print to stdout) |

### MongoDB MCP

| MCP Tool | Parameters | Data Source |
|----------|-----------|-------------|
| `get_customers_by_tier` | `tier: str, limit: int` | `casino_crm.customers` |
| `get_prospects` | `limit: int` | `casino_crm.prospects` |
| `get_all_vip_customers` | `limit: int` | `casino_crm.customers` |
| `get_high_spend_customers` | `min_spend: int, limit: int` | `casino_crm.customers` |
| `search_customers` | `query: str, limit: int` | `casino_crm.customers` |
| `get_customer_count_by_tier` | — | `casino_crm.customers` (aggregation) |

### ImageGen MCP

| MCP Tool | Parameters | Returns |
|----------|-----------|---------|
| `generate_campaign_image` | `campaign_name, hotel_name, theme, description, width, height` | `{image_url, image_id, prompt, status}` |
| `generate_campaign_image_b64` | Same | `{data_uri, image_id, prompt, status}` |

| HTTP Route | Purpose |
|------------|---------|
| `GET /images/{id}.png` | Serve generated images from in-memory store |
| `GET /health` | Health check with stored image count |

### KAgent Discovery Labels

Both MCP deployments carry these labels for KAgent integration:

```yaml
kagenti.io/type: tool
protocol.kagenti.io/mcp: ""
kagenti.io/transport: streamable_http
app.kubernetes.io/name: <service-name>
```

---

*Document maintained by: AI Demo Team*  
*Architecture based on Elastic Newsroom A2A pattern*
