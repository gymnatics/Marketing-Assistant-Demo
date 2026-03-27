# Macau Casino Marketing AI Assistant Demo

An AI-powered Marketing Campaign Assistant for Macau Casinos, designed to accelerate marketing campaign creation for high-net-worth customers. The system leverages a multi-agent architecture running on Red Hat OpenShift AI (RHOAI) to:

- Generate marketing webpages through natural language conversation
- Automatically containerize and deploy campaigns to OpenShift
- Provide human-in-the-loop approval workflows
- Generate and send marketing emails to customers

## Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              User Interface                                  │
│                         (Streamlit Chatbot UI)                              │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Backend / Agent Orchestrator                         │
│                              (LangGraph)                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ Coder Agent  │  │ K8s/DevOps   │  │  Marketing   │  │  Customer    │    │
│  │              │  │    Agent     │  │    Agent     │  │   Agent      │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        OpenShift Platform                                    │
│  ┌──────────────────────────┐  ┌──────────────────────────┐                 │
│  │     Dev Namespace        │  │     Prod Namespace       │                 │
│  │  (Preview Deployments)   │  │  (Live Deployments)      │                 │
│  └──────────────────────────┘  └──────────────────────────┘                 │
│  ┌──────────────────────────┐                                               │
│  │   RHOAI Model Serving    │                                               │
│  │   (vLLM + Qwen Models)   │                                               │
│  └──────────────────────────┘                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Agent Architecture

| Agent | Purpose | Model |
|-------|---------|-------|
| **Coder Agent** | Generate HTML/CSS/JS for marketing webpages | Qwen2.5-Coder-32B |
| **K8s/DevOps Agent** | Build and deploy containers to OpenShift | Qwen2.5-Coder-32B |
| **Marketing Agent** | Generate marketing copy and emails (EN/中文) | Qwen3-32B |
| **Customer Agent** | Retrieve customer profiles for personalization | Qwen3-32B |

## User Flow

1. **Welcome** - User selects "Create Campaign"
2. **Campaign Details** - User provides campaign name, description, dates, and target audience
3. **Theme Selection** - User selects from 4 visual themes (Luxury Gold, Festive Red, Modern Black, Classic Casino)
4. **Generation** - AI agents generate webpage, build container, deploy to preview
5. **Preview** - User reviews campaign with QR code, can edit or go live
6. **Go Live** - Campaign deployed to production, marketing emails generated

## Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | Streamlit |
| Backend | Python 3.11+, LangGraph |
| Models | Qwen2.5-Coder-32B, Qwen3-32B (via vLLM) |
| Database | MongoDB (customer profiles) |
| Platform | Red Hat OpenShift AI (RHOAI) |
| Container Runtime | Podman/Buildah |

## Project Structure

```
.
├── app.py                 # Streamlit UI application
├── config/
│   └── settings.py        # Configuration management
├── src/
│   ├── agents/
│   │   ├── coder_agent.py     # HTML/CSS/JS generation
│   │   ├── k8s_agent.py       # Kubernetes deployments
│   │   ├── marketing_agent.py # Email content generation
│   │   └── customer_agent.py  # Customer data retrieval
│   ├── orchestrator.py    # LangGraph workflow
│   └── state.py           # Shared state definitions
├── k8s/                   # Kubernetes manifests
├── Dockerfile             # Container image definition
├── deploy.sh              # Deployment script
└── requirements.txt       # Python dependencies
```

## Setup

### Prerequisites

- Python 3.11+
- Access to OpenShift cluster with RHOAI
- Qwen models deployed via vLLM
- MongoDB instance (optional, uses mock data if unavailable)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/gymnatics/Marketing-Assistant-Demo.git
   cd Marketing-Assistant-Demo
   ```

2. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your model endpoints and tokens
   ```

5. Run locally:
   ```bash
   streamlit run app.py
   ```

### Deploy to OpenShift

```bash
# Login to OpenShift
oc login --token=<your-token> --server=<your-cluster>

# Run deployment script
./deploy.sh
```

## Campaign Themes

| Theme | Colors | Use Case |
|-------|--------|----------|
| **Luxury Gold** | Gold, Black, White | VIP exclusive offers |
| **Festive Red** | Red, Gold, White | Holiday promotions (CNY) |
| **Modern Black** | Black, Silver, Cyan | New member promotions |
| **Classic Casino** | Green, Gold, Burgundy | Gaming promotions |

## Features

- **Multi-language Support**: English and Chinese (Simplified) content generation
- **Human-in-the-Loop**: Preview and approval workflow before going live
- **Streaming LLM Calls**: Avoids timeout issues with long-running generation
- **QR Code Generation**: For easy mobile access to campaigns
- **Email Simulation**: Preview marketing emails without actual sending

## License

MIT License
