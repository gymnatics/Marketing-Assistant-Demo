# Marketing Campaign Assistant v2

A microservices-based AI marketing campaign assistant using A2A (Agent-to-Agent) protocol for multi-agent collaboration.

## Architecture

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
```

## Components

| Component | Port | Purpose |
|-----------|------|---------|
| React Dashboard | 3000 | Campaign portal UI |
| Campaign API | 5000 | API gateway |
| Event Hub | 5001 | Real-time event streaming (SSE) |
| Campaign Director | 8080 | Workflow orchestration (LangGraph) |
| Creative Producer | 8081 | HTML/CSS generation |
| Customer Analyst | 8082 | Customer profile retrieval |
| Delivery Manager | 8083 | Email generation + K8s deployment |
| MongoDB MCP | 8090 | Customer database access (FastMCP) |

## Quick Start

### Local Development

1. Set environment variables:
```bash
cp .env.example .env
# Edit .env with your model endpoints and tokens
```

2. Start all services:
```bash
docker-compose up
```

3. Access the dashboard:
- Frontend: http://localhost:3000
- API: http://localhost:5000
- Event Hub: http://localhost:5001

### OpenShift Deployment

1. Create namespace and config:
```bash
oc apply -f k8s/namespace.yaml
oc apply -f k8s/configmap.yaml
oc apply -f k8s/secret-example.yaml  # Copy to secret.yaml and edit with your tokens first
```

2. Deploy MCP server:
```bash
oc apply -f k8s/mcp/
```

3. Deploy agents:
```bash
oc apply -f k8s/agents/
```

4. Deploy API layer:
```bash
oc apply -f k8s/api/
```

5. Deploy frontend:
```bash
oc apply -f k8s/frontend/
```

## Workflow

1. **Create Campaign** - Enter campaign details and dates
2. **Select Theme** - Choose visual style (Luxury Gold, Festive Red, etc.)
3. **Generate Landing Page** - Creative Producer generates HTML
4. **Preview Landing Page** - Review and edit if needed
5. **Preview Email & Recipients** - See email content and recipient list
6. **Confirmation** - Final review before going live
7. **Go Live** - Deploy to production and send emails

## Technology Stack

- **Frontend**: React 18, TypeScript, Headless UI, Heroicons
- **API Gateway**: Flask 3.0, Flask-CORS
- **Agent Protocol**: A2A SDK 0.3.25 (`a2a-sdk[http-server]`)
- **Agent Servers**: Starlette + Uvicorn (via `A2AStarletteApplication`)
- **Orchestration**: LangGraph 0.2+, LangChain 0.2+
- **MCP Server**: FastMCP 2.12+ (custom Starlette REST wrapper)
- **LLM Inference**: vLLM on RHOAI (Qwen2.5-Coder-32B, Qwen3-32B)
- **Database**: MongoDB 7

## Key Improvements from v1

1. **True Microservices**: Each agent runs as a separate pod
2. **A2A Protocol**: Standardized inter-agent communication
3. **Business-Friendly UI**: React dashboard with visual workflow
4. **Preview Before Commit**: See email content and recipients before going live
5. **MCP Integration**: MongoDB customer data via FastMCP server
