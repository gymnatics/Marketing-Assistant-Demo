# Product Requirements Document (PRD)
# Marketing Campaign Assistant v2 - Microservices Architecture

**Version:** 2.0  
**Last Updated:** March 30, 2026  
**Status:** In Development  
**Platform:** Red Hat OpenShift AI 3.3

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Agent Definitions](#3-agent-definitions)
4. [User Interface](#4-user-interface)
5. [Workflow](#5-workflow)
6. [Technical Implementation](#6-technical-implementation)
7. [API Specifications](#7-api-specifications)
8. [Deployment](#8-deployment)

---

## 1. Executive Summary

### What Changed from v1

| Aspect | v1 (Monolith) | v2 (Microservices) |
|--------|---------------|-------------------|
| Architecture | Single Streamlit app | Separate A2A agent microservices |
| UI | Chatbot-style | Campaign Dashboard Portal |
| Orchestration | LangGraph in-process | A2A protocol between services |
| MCP | Not used | MongoDB wrapped in FastMCP |
| Workflow | Email shown after Go Live | Preview everything before Go Live |
| Target Audience | Developers | C-Suite executives |

### Key Improvements

1. **True Microservices**: Each agent runs as a separate pod, enabling AgentOps observability
2. **A2A Protocol**: Standardized inter-agent communication following industry patterns
3. **Business-Friendly UI**: React dashboard with visual workflow navigator
4. **Preview Before Commit**: Users see email content and recipients before going live
5. **MCP Integration**: MongoDB customer data exposed via FastMCP server

---

## 2. Architecture Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACE                                  │
│                         React Campaign Dashboard                             │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ HTTP
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API LAYER                                       │
│  ┌──────────────────────────┐  ┌──────────────────────────┐                 │
│  │      Campaign API        │  │       Event Hub          │                 │
│  │    (Flask Gateway)       │  │   (SSE Broadcasting)     │                 │
│  └──────────────────────────┘  └──────────────────────────┘                 │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ A2A Protocol
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CORE AGENTS (A2A Protocol)                          │
│                                                                              │
│  ┌──────────────────┐                                                       │
│  │ Campaign Director│ ◄── Coordinator (LangGraph)                          │
│  │   (Orchestrator) │                                                       │
│  └────────┬─────────┘                                                       │
│           │                                                                  │
│     ┌─────┼─────────────────┬─────────────────┐                             │
│     ▼     ▼                 ▼                 ▼                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │  Creative    │  │  Customer    │  │  Delivery    │                      │
│  │  Producer    │  │  Analyst     │  │  Manager     │                      │
│  │ (HTML Gen)   │  │ (Profiles)   │  │ (Email+K8s)  │                      │
│  └──────────────┘  └──────────────┘  └──────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   MongoDB MCP    │  │   Qwen Models    │  │    OpenShift     │
│   (FastMCP)      │  │   (vLLM)         │  │   (Deployment)   │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

### Component Summary

| Component | Technology | Port | Purpose |
|-----------|------------|------|---------|
| React Dashboard | React 18 + TypeScript | 3000 | Campaign portal UI |
| Campaign API | Flask | 5000 | API gateway |
| Event Hub | Flask + SSE | 5001 | Real-time event streaming |
| Campaign Director | Python + A2A SDK | 8080 | Workflow orchestration |
| Creative Producer | Python + A2A SDK | 8081 | HTML/CSS generation |
| Customer Analyst | Python + A2A SDK | 8082 | Customer profile retrieval |
| Delivery Manager | Python + A2A SDK | 8083 | Email generation + K8s deploy |
| MongoDB MCP | FastMCP | 8090 | Customer database access |

---

## 3. Agent Definitions

### Campaign Director (Coordinator)

**Role:** Orchestrates the entire campaign workflow, delegates tasks to specialized agents.

**Agent Card:**
```json
{
  "name": "Campaign Director",
  "description": "Coordinates marketing campaign creation workflow",
  "version": "1.0.0",
  "protocol_version": "0.3.0",
  "skills": [
    {
      "name": "create_campaign",
      "description": "Orchestrate full campaign creation workflow"
    },
    {
      "name": "approve_campaign",
      "description": "Finalize and deploy approved campaign"
    }
  ]
}
```

**Responsibilities:**
- Receive campaign requests from API
- Delegate HTML generation to Creative Producer
- Delegate customer retrieval to Customer Analyst
- Delegate email generation and deployment to Delivery Manager
- Manage workflow state and human-in-the-loop approvals
- Publish events to Event Hub for UI updates

---

### Creative Producer (HTML Generation)

**Role:** Generates luxury marketing landing pages with HTML/CSS/JS.

**Agent Card:**
```json
{
  "name": "Creative Producer",
  "description": "Generates marketing landing pages with HTML/CSS/JS",
  "version": "1.0.0",
  "protocol_version": "0.3.0",
  "skills": [
    {
      "name": "generate_landing_page",
      "description": "Create a luxury marketing landing page",
      "input_schema": {
        "type": "object",
        "properties": {
          "campaign_name": {"type": "string"},
          "description": {"type": "string"},
          "hotel_name": {"type": "string"},
          "theme": {"type": "string"},
          "start_date": {"type": "string"},
          "end_date": {"type": "string"}
        },
        "required": ["campaign_name", "description", "theme"]
      }
    }
  ]
}
```

**Model:** Qwen2.5-Coder-32B-FP8

---

### Customer Analyst (Profile Retrieval)

**Role:** Retrieves customer profiles based on target audience criteria.

**Agent Card:**
```json
{
  "name": "Customer Analyst",
  "description": "Retrieves VIP customer profiles for campaign targeting",
  "version": "1.0.0",
  "protocol_version": "0.3.0",
  "skills": [
    {
      "name": "get_target_customers",
      "description": "Retrieve customers matching target audience",
      "input_schema": {
        "type": "object",
        "properties": {
          "target_audience": {"type": "string"},
          "limit": {"type": "integer", "default": 50}
        },
        "required": ["target_audience"]
      }
    }
  ]
}
```

**Integration:** Uses MCP to query MongoDB customer database

---

### Delivery Manager (Email + Deployment)

**Role:** Generates marketing emails and deploys campaigns to OpenShift.

**Architecture:** 3-layer A2A SDK pattern:
- `agent.py` — Pure business logic (`DeliveryManagerAgent` class)
- `agent_executor.py` — A2A `AgentExecutor` bridge (JSON dispatch)
- `__main__.py` — Entry point with `AgentCard`, skills, health check

**Agent Card (a2a-sdk `AgentCard`):**
```json
{
  "name": "Delivery Manager",
  "description": "Generates marketing emails and deploys campaigns to OpenShift",
  "version": "1.0.0",
  "skills": [
    {"id": "generate_email", "name": "Generate Email", "description": "Generate marketing email content in English and Chinese"},
    {"id": "deploy_preview", "name": "Deploy Preview", "description": "Deploy campaign landing page to preview environment"},
    {"id": "deploy_production", "name": "Deploy Production", "description": "Deploy campaign landing page to production"},
    {"id": "send_emails", "name": "Send Emails", "description": "Send marketing emails to customer list (simulated)"}
  ]
}
```

**Model:** Qwen3-32B-FP8-Dynamic  
**Integration:** Kubernetes Python client for OpenShift deployment  
**Dependencies:** `a2a-sdk[http-server]>=0.3.25`, `httpx`, `kubernetes>=29.0.0`

---

## 4. User Interface

### Design Principles (C-Suite Friendly)

1. **Clean and Minimal**: Large visual elements, no technical jargon
2. **Visual Progress**: Clear workflow navigator showing current step
3. **Preview Everything**: See landing page, email, and recipients before committing
4. **One-Click Actions**: Simple "Next", "Back", "Go Live" buttons
5. **Real-Time Feedback**: Agent activity shown via SSE streaming

### Screen Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Dashboard     │────▶│  Campaign Form  │────▶│ Theme Selection │
│  (Campaign List)│     │  (Details+Dates)│     │  (Visual Picker)│
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                         │
         ┌───────────────────────────────────────────────┘
         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Landing Page   │────▶│  Email Preview  │────▶│   Confirmation  │
│    Preview      │     │  + Recipients   │     │   (Go Live)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                         │
                                                         ▼
                                                ┌─────────────────┐
                                                │    Success      │
                                                │  (Live URLs)    │
                                                └─────────────────┘
```

### Key Components

| Component | Purpose |
|-----------|---------|
| `Dashboard` | Campaign list with status cards |
| `CampaignWizard` | Step-by-step campaign creation |
| `WorkflowNavigator` | Visual progress indicator |
| `ThemeSelector` | Visual theme picker with color previews |
| `LandingPagePreview` | Iframe preview of generated page |
| `EmailPreview` | Email content preview with recipient list |
| `AgentStatusPanel` | Real-time agent activity display |

---

## 5. Workflow

### New Workflow (v2)

```
Step 1: Create Campaign
├── Campaign name
├── Description
├── Hotel name
├── Target audience
├── Start date (date picker)
└── End date (date picker)

Step 2: Select Theme
├── Luxury Gold
├── Festive Red
├── Modern Black
└── Classic Casino

Step 3: Generate & Preview Landing Page
├── Creative Producer generates HTML
├── Delivery Manager deploys to preview
├── User reviews landing page
└── [Edit] or [Continue]

Step 4: Preview Email & Recipients    ◄── NEW (before Go Live)
├── Customer Analyst retrieves customers
├── Delivery Manager generates email content
├── User reviews:
│   ├── Email content (EN + ZH)
│   └── Recipient list with count
└── [Edit] or [Continue]

Step 5: Confirmation
├── Summary of all details
├── Landing page URL
├── Email preview
├── Recipient count
└── [Go Live] button

Step 6: Go Live
├── Deploy to production
├── Send emails (simulated)
└── Show success with live URLs
```

### Human-in-the-Loop Points

1. **After Landing Page Preview**: User can edit theme or details
2. **After Email Preview**: User can edit campaign before sending
3. **Confirmation Screen**: Final review before Go Live

---

## 6. Technical Implementation

### Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18, TypeScript, Tailwind CSS |
| API Gateway | Flask 3.0 |
| Event Streaming | Flask-SSE |
| Agent Protocol | A2A SDK 0.3.25 |
| Orchestration | LangGraph 0.2+ |
| MCP Server | FastMCP 2.12+ |
| LLM Inference | vLLM on RHOAI |
| Database | MongoDB |
| Container Runtime | Podman |
| Platform | OpenShift 4.19+ / RHOAI 3.3 |

### Dependencies

```
# services/requirements-common.txt
a2a-sdk>=0.3.25
httpx>=0.27.0
pydantic>=2.0.0

# services/campaign-director/requirements.txt
langgraph>=0.2.0
langchain>=0.2.0

# services/mongodb-mcp/requirements.txt
fastmcp>=2.12.5
pymongo>=4.6.0

# services/delivery-manager/requirements.txt
kubernetes>=29.0.0
qrcode>=7.4.0
pillow>=10.0.0
```

### Environment Variables

```bash
# Model endpoints
CODE_MODEL_ENDPOINT=https://qwen25-coder-32b-fp8-{namespace}.{cluster_domain}/v1
CODE_MODEL_NAME=qwen25-coder-32b-fp8
LANG_MODEL_ENDPOINT=https://qwen3-32b-fp8-dynamic-{namespace}.{cluster_domain}/v1
LANG_MODEL_NAME=qwen3-32b-fp8-dynamic

# Agent endpoints (internal)
CAMPAIGN_DIRECTOR_URL=http://campaign-director:8080
CREATIVE_PRODUCER_URL=http://creative-producer:8081
CUSTOMER_ANALYST_URL=http://customer-analyst:8082
DELIVERY_MANAGER_URL=http://delivery-manager:8083

# MCP
MONGODB_MCP_URL=http://mongodb-mcp:8090

# MongoDB
MONGODB_URI=mongodb://mongodb:27017
MONGODB_DATABASE=casino_crm

# OpenShift
CLUSTER_DOMAIN=apps.cluster.example.com
DEV_NAMESPACE=marketing-assistant-dev
PROD_NAMESPACE=marketing-assistant-prod

# Event Hub
EVENT_HUB_URL=http://event-hub:5001
```

---

## 7. API Specifications

### Campaign API Endpoints

```
POST /api/campaigns
  Create new campaign, returns campaign_id

GET /api/campaigns
  List all campaigns

GET /api/campaigns/{id}
  Get campaign details and status

POST /api/campaigns/{id}/generate
  Trigger landing page generation

POST /api/campaigns/{id}/preview-email
  Trigger email and customer retrieval

POST /api/campaigns/{id}/approve
  Go live - deploy to production and send emails

DELETE /api/campaigns/{id}
  Cancel/delete campaign
```

### Event Hub SSE

```
GET /events/{campaign_id}
  SSE stream for real-time updates

Event types:
- agent_started: {agent: "Creative Producer", task: "Generating landing page"}
- agent_completed: {agent: "Creative Producer", result: {...}}
- agent_error: {agent: "...", error: "..."}
- workflow_status: {step: "preview_ready", data: {...}}
```

### A2A Agent Endpoints

Each agent uses the official `a2a-sdk` with a 3-layer architecture:
- **`agent.py`** – Pure business logic (no framework deps)
- **`agent_executor.py`** – `AgentExecutor` bridge to a2a-sdk
- **`__main__.py`** – `A2AStarletteApplication` entry point with `AgentCard`

Standard endpoints exposed by a2a-sdk:
```
GET /.well-known/agent.json
  Agent card discovery (AgentCard via a2a-sdk)

POST /
  A2A message/task endpoint (DefaultRequestHandler)

GET /health
  Health check (custom Starlette route)
```

**Refactored agents:** Creative Producer (complete), Customer Analyst (complete)

**Pending refactor:** Delivery Manager, Campaign Director

---

## 8. Deployment

### Kubernetes Resources per Service

Each service requires:
- Deployment
- Service
- ConfigMap (environment)
- Optional: Route (for external access)

### Namespace Structure

```
marketing-assistant/           # Main namespace
├── campaign-api              # API gateway (external route)
├── event-hub                 # SSE service (external route)
├── campaign-director         # Orchestrator
├── creative-producer         # HTML generation
├── customer-analyst          # Customer profiles
├── delivery-manager          # Email + deploy
├── mongodb-mcp               # MCP server
├── mongodb                   # Database
└── frontend                  # React app (external route)

marketing-assistant-dev/       # Preview deployments
└── (generated campaigns)

marketing-assistant-prod/      # Production deployments
└── (approved campaigns)
```

### Local Development

```bash
# Start all services
docker-compose up

# Access
# - Frontend: http://localhost:3000
# - API: http://localhost:5000
# - Event Hub: http://localhost:5001
```

---

## Appendix: Migration from v1

### Code Reuse

| v1 File | v2 Location | Changes |
|---------|-------------|---------|
| `src/agents/coder_agent.py` | `services/creative-producer/` | 3-layer a2a-sdk pattern (agent.py, agent_executor.py, __main__.py) |
| `src/agents/customer_agent.py` | `services/customer-analyst/` | Add MCP client |
| `src/agents/marketing_agent.py` | `services/delivery-manager/` | Combine with k8s |
| `src/agents/k8s_agent.py` | `services/delivery-manager/` | Merge into Delivery Manager |
| `src/state.py` | `shared/models.py` | Extract themes, shared types |
| `config/settings.py` | Per-service config | Split per service |

### Phase 2: LlamaStack Integration (Optional)

If LlamaStack integration is desired later:
1. Replace vLLM direct calls with LlamaStack Inference API
2. Use LlamaStack Tools API alongside MCP
3. Keep A2A microservices structure (LlamaStack doesn't replace A2A)

---

## Appendix: Known Issues and Fixes

### Issue 1: MongoDB MCP Server Unreachable (Connection Refused)
- **Symptom**: Customer Analyst fails with "Connection refused" when calling MongoDB MCP
- **Root Cause**: FastMCP `mcp.run()` binds to `127.0.0.1` (localhost only), not accessible from other pods
- **Fix**: Replaced `mcp.run()` with a custom Starlette app binding to `0.0.0.0`, exposing REST `/tools/{name}` endpoints for direct HTTP tool calls

### Issue 2: Workflow Continues After Node Failure
- **Symptom**: Customer retrieval fails but email generation proceeds anyway, producing emails without customer data
- **Root Cause**: LangGraph `add_edge()` always routes to the next node regardless of state
- **Fix**: Added `add_conditional_edges()` with a `_check_failed()` function that routes to END when `status == "failed"`

### Issue 3: "All connection attempts failed" Error Banner
- **Symptom**: Red error banner appears intermittently during campaign generation
- **Root Cause**: SSE EventSource connection to Event Hub fails/reconnects, triggering error state
- **Fix**: SSE `onerror` handler now closes the connection cleanly; polling continues independently

### Issue 4: Broken QR Code Image in Generated Landing Pages
- **Symptom**: QR code section shows broken image placeholder
- **Root Cause**: LLM generates `<img>` tags with invalid/placeholder URLs for QR codes
- **Status**: Cosmetic issue - QR code generation requires an actual QR code service integration (e.g., goqr.me API)

### Issue 5: OpenShift Image Caching (imagePullPolicy)
- **Symptom**: Pods continue running old code after image push and rollout restart
- **Root Cause**: Default `imagePullPolicy: IfNotPresent` uses cached images when tag is the same
- **Fix**: Added `imagePullPolicy: Always` to all deployment manifests

### Issue 6: Secret Tokens Committed to Git
- **Symptom**: GitGuardian alert for Kubernetes service account tokens in git history
- **Root Cause**: `k8s/secret.yaml` was tracked before `.gitignore` was updated
- **Fix**: Purged from git history via `git filter-branch`, added `secret-example.yaml` template, strengthened `.gitignore` patterns

---

*Document maintained by: AI Demo Team*  
*Based on Elastic Blog A2A Architecture Pattern*
