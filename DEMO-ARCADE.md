# Arcade Demo Story — Simon Casino Resort AI Campaign Manager

## Overview

Two interactive arcade demos showcasing AI agent orchestration on Red Hat OpenShift AI:

1. **Arcade 1: AI Campaign Manager** — Business value demo for C-Suite executives
2. **Arcade 2: Agent Governance with KAgenti** — Platform value demo for technical leaders

---

## Arcade 1: AI Campaign Manager

**Title:** From Brief to Campaign in 3 Minutes

**Target Audience:** C-Suite executives, casino marketing directors, IT decision-makers

**Opening Hook:** Your marketing team takes 2-3 weeks to launch a campaign — designers, copywriters, translators, IT for deployment. What if AI agents could do it in 3 minutes, on YOUR infrastructure, with YOUR data, under YOUR control?

### Act 1: The Brief (30 seconds)

**What the user does:**
- Opens the Campaign Dashboard
- Clicks "Create New Campaign"
- Uses Quick Start dropdown to auto-fill "CNY VIP Gala"
- Shows the branded hotel venue dropdown

**What to highlight:**
- No technical knowledge needed — marketing executives drive this
- Pre-built templates for quick demos, or type your own
- Branded experience — Simon Casino Resort, not a generic tool

**Talking point:** "The interface is designed for business users, not engineers. Define your campaign strategy, pick your audience, and let the AI handle the rest."

### Act 2: AI Safety — Guardrails (30 seconds)

**What the user does:**
- Uses Quick Start to select a guardrails test (e.g., "Competitor Name" or "Inappropriate Language")
- Clicks Next — shows the red rejection banner
- Edits to a valid description — passes validation

**What to highlight:**
- 4-layer guardrails: Regex, TrustyAI HAP (Granite Guardian), TrustyAI Prompt Injection (DeBERTa v3), Policy Guardian (Qwen3)
- Instant feedback — no restart needed, edit and retry
- Business policy enforcement — no unrealistic discounts, no competitor mentions

**Talking point:** "Every input passes through 4 layers of AI safety before anything is generated. This protects your brand, your compliance, and your reputation."

### Act 3: AI Generation (60 seconds)

**What the user does:**
- Selects a theme (e.g., Luxury Gold or Classic Casino)
- Clicks "Generate" — watches real-time agent activity
- Views the AI-generated hero image + landing page

**What to highlight:**
- Real-time SSE events showing agent collaboration
- FLUX.2 generates a custom hero banner image
- Qwen Coder designs the landing page with professional styling
- Every regeneration produces a different design

**Talking point:** "Three AI models are collaborating in real-time — one generates the image, one designs the page, and one orchestrates the workflow. All running on your GPUs, on your infrastructure."

### Act 4: Personalization (30 seconds)

**What the user does:**
- On the preview step, selects different VIP customers from the dropdown
- Shows the landing page changing per customer (name, tier badge, greeting)

**What to highlight:**
- Same URL, different experience per customer
- Real-time personalization via MCP (Model Context Protocol) querying MongoDB
- VIP members see "Platinum VIP", prospects see "Exclusive Invitee"

**Talking point:** "Each customer gets a page crafted just for them. The AI personalizes in real-time by querying your customer database through MCP — an open standard for giving AI access to your data."

### Act 5: Go Live (30 seconds)

**What the user does:**
- Clicks "Prepare Emails" — AI retrieves customers and generates email content
- Reviews email preview and recipient list
- Clicks "Go Live" — deploys to production, sends emails
- Checks the Inbox — personalized emails per recipient with QR codes

**What to highlight:**
- Bilingual email generation (or English-only depending on config)
- Human-in-the-loop — review everything before committing
- One-click deployment to OpenShift
- Gmail-style inbox shows what each customer received

**Talking point:** "From brief to live campaign in under 3 minutes. Landing page deployed, emails sent, QR codes generated — all reviewed and approved by a human before going live."

### Closing

**Architecture one-liner:** "5 AI agents communicating via A2A protocol, accessing tools via MCP, protected by TrustyAI guardrails, running 3 open-source GPU models on Red Hat OpenShift AI — generating a complete marketing campaign in under 3 minutes."

**Key technologies:** A2A (Google), MCP (Anthropic), LangGraph, TrustyAI, KServe, vLLM, OpenShift AI

---

## Arcade 2: Agent Governance with KAgenti

**Title:** Secure, Observe, and Govern Your AI Agents

**Target Audience:** Platform engineers, security architects, AI infrastructure leads

**Opening Hook:** You've deployed AI agents. Now how do you know what they're doing, who they're talking to, and whether they have the right permissions?

### Act 1: Agent Discovery (30 seconds)

**What the user does:**
- Opens KAgenti dashboard
- Shows the Agent Catalog with all 5 agents discovered automatically
- Clicks on an agent to see details, skills, and security schemes

**What to highlight:**
- Kubernetes-native agent discovery via labels
- A2A agent cards with declared capabilities and security schemes
- No manual registration — deploy an agent, KAgenti finds it

**Talking point:** "KAgenti discovers your agents automatically. Every agent declares its capabilities through the A2A protocol — what it can do, what skills it has, and how it authenticates."

### Act 2: Agent Chat — Talk to Your Agents (60 seconds)

**What the user does:**
- Clicks "Chat" on the Customer Analyst agent
- Types "list all platinum members"
- Shows the agent querying MongoDB via MCP and returning results
- Types "list all gold tier members only"
- Shows filtered results

**What to highlight:**
- KAgenti UI talks to agents via A2A protocol
- The agent uses LLM tool calling to decide which MCP tool to invoke
- Real-time interaction with enterprise data

**Talking point:** "You can interact with any agent directly through the KAgenti dashboard. The agent uses an LLM to understand your request and decides which database tool to call — all through open standards."

### Act 3: Role-Based Access Control (60 seconds)

**What the user does:**
- Logs out and logs in as a different Keycloak user (e.g., "gold-user")
- Asks the same question — "list all platinum members"
- Gets restricted results (gold tier only, no platinum)
- Logs back in as admin — sees all tiers

**What to highlight:**
- Keycloak OIDC authentication
- JWT token carries user scopes/roles
- MongoDB MCP filters data based on user permissions
- Zero-trust: every request is authenticated and scoped

**Talking point:** "Different users, different data access. The JWT token from Keycloak carries the user's permissions all the way through to the database query. This is zero-trust AI governance in action."

### Act 4: Observability (30 seconds)

**What the user does:**
- Opens the Observability tab in KAgenti
- Shows agent call traces, latency, and tool invocations
- Shows OpenTelemetry data flowing through the system

**What to highlight:**
- Full observability of agent-to-agent and agent-to-tool calls
- Traces show the complete request path
- Monitor which agents are active, which tools are being called

**Talking point:** "Every agent interaction is traced and observable. You can see exactly what happened, how long it took, and what tools were used — critical for compliance and debugging."

### Closing

**Platform one-liner:** "KAgenti gives you a unified control plane for AI agents — discover, chat, secure, and observe every agent on your Kubernetes cluster, using open standards like A2A and MCP."

**Key technologies:** KAgenti, Keycloak (OIDC), SPIFFE/SPIRE, A2A Protocol, MCP, OpenTelemetry

---

## How the Two Arcades Connect

| Arcade 1 (Business) | Arcade 2 (Platform) |
|---------------------|-------------------|
| "Look what AI agents can BUILD" | "Look how you GOVERN AI agents" |
| Campaign Dashboard UI | KAgenti Dashboard UI |
| 5 agents collaborating | Same 5 agents — discovered and secured |
| Guardrails protect content | RBAC protects data access |
| MCP accesses customer data | Same MCP — now with auth scoping |
| Marketing executives | Platform engineers |

**Stitch point:** "The same agents that generated that campaign in 3 minutes? They're all governed by KAgenti — discovered automatically, secured with zero-trust authentication, and fully observable."

---

## Prerequisites for Each Arcade

### Arcade 1 (Campaign Manager)
- OpenShift AI cluster with 3 GPU models served
- App deployed via `./deploy.sh`
- Basic campaign seeded via `./seed-basic-campaign.sh`
- Clean slate via `./reset-demo.sh` before each run

### Arcade 2 (KAgenti)
- Everything from Arcade 1
- KAgenti platform deployed on the cluster
- Keycloak configured with demo users and scopes (for Act 3)
- Port 8080 mapped on all agent Services
