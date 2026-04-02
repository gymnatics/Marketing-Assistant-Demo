# Demo Script — Grand Lisboa Palace AI Campaign Manager
## For EBC Macau Casino Demo

---

## Pre-Demo Setup

- [ ] Open browser to the dashboard: `https://marketing-assistant-v2-marketing-assistant-v2.apps.cluster-qf44v.qf44v.sandbox543.opentlc.com`
- [ ] Clear any test campaigns (restart campaign-director pod if needed)
- [ ] Optionally have one pre-generated campaign already showing on the dashboard
- [ ] Keep a second tab ready for the generated landing page

---

## The Story (1 minute)

> "Imagine you're running marketing for a luxury casino resort in Macau. You need to launch a Chinese New Year campaign — a premium landing page, personalized emails in English and Chinese, targeted to your VIP platinum members. Normally this takes your team 2-3 weeks — designers, copywriters, translators, IT for deployment."
>
> "What if AI agents could do this in under 3 minutes?"
>
> "This system runs entirely on Red Hat OpenShift AI — your infrastructure, your data, your control. Let me show you."

---

## Live Demo Flow (5-6 minutes)

### Step 1: Create Campaign (30 seconds)

**Action:** Click "Create New Campaign"

**Fill in:**
- Name: `Chinese New Year VIP Gala`
- Description: `An exclusive celebration for our most valued guests. Premium dining, private gaming, entertainment, and luxury accommodation packages.`
- Hotel: `Grand Lisboa Palace`
- Audience: `Platinum members`
- Dates: Pick dates about 2 weeks out
- Click **Next**

**Say:** "We define the campaign strategy — name, target audience, dates. Simple form, no technical knowledge needed."

### Step 2: Select Theme (15 seconds)

**Action:** Click on **Luxury Gold** theme card, then click **Next: Generate Assets**

**Say:** "Choose a visual identity. The AI will match everything to this theme — colors, mood, imagery."

### Step 3: Watch Agents Work (60-90 seconds)

**Action:** Watch the progress banner and agent event log

**Say while waiting:**
> "Now watch what happens. Multiple AI agents are collaborating in real-time:"
>
> "First — the **Creative Producer** agent calls our **image generation AI** to create a custom hero banner. This is FLUX.2, a diffusion model running on our GPU."
>
> "Then it hands that image to our **code generation AI** — Qwen, an open-source model — which designs a complete landing page around it. Unique layout, animations, responsive design."
>
> "Finally, the **Delivery Manager** deploys it live to OpenShift — real infrastructure, real URL."
>
> *Point to the SSE event log:* "You can see each agent reporting in as it works."

### Step 4: Preview Landing Page (30 seconds)

**Action:** Click the preview URL or QR code to open the landing page

**Say:** "This was generated from scratch by AI — the hero image, the layout, the copy, the Chinese translations. Every time you regenerate, you get a completely different design."

**Optional:** Click **Regenerate** to show layout variation.

### Step 5: Prepare Emails (45 seconds)

**Action:** Click **Prepare Emails**

**Say while waiting:**
> "Now our **Customer Analyst** agent uses an LLM to figure out which customers to target. It has access to the customer database through an **MCP tool** — the Model Context Protocol, an open standard for giving AI access to your data."
>
> "It retrieves the platinum VIP members, then the **Delivery Manager** generates personalized emails in both English and Chinese."

**Action:** Show the email preview (toggle EN/ZH), point to the recipient list on the right

**Say:** "Bilingual emails, auto-generated. Your team reviews and approves — human in the loop."

### Step 6: Go Live (30 seconds)

**Action:** Click through to confirmation, then **Go Live Now**

**Say:** "One click — deploys to production on OpenShift, sends to all recipients. The campaign is live."

**Action:** Show the success screen with production URL and QR code

---

## Key Talking Points (for Q&A)

### For Casino Executives

| Question | Answer |
|----------|--------|
| "How long does this take?" | "Under 3 minutes for a complete campaign — landing page, emails, deployment. Traditionally 2-3 weeks." |
| "Can we customize the branding?" | "Absolutely. The themes, colors, hotel name, and logo are all configurable. The AI adapts to your brand." |
| "Is this safe for our customer data?" | "Everything runs on YOUR infrastructure — Red Hat OpenShift AI on-premise or in your cloud. Customer data never leaves your environment." |
| "What about Chinese language?" | "Built-in. Landing pages and emails are bilingual by default — English and Simplified Chinese." |
| "Can our team use this?" | "The interface is designed for marketing executives, not engineers. Create, review, approve, launch." |

### For Technical Stakeholders

| Topic | Detail |
|-------|--------|
| **Agent Protocol** | A2A (Agent-to-Agent) SDK — Google's open standard for agent communication |
| **Tool Access** | MCP (Model Context Protocol) — Anthropic's open standard for giving AI access to databases/tools |
| **Orchestration** | LangGraph for workflow coordination with error handling |
| **Models** | 3 open-source models on 3 GPUs: Qwen Coder (HTML), Qwen3 (email + tool calling), FLUX.2 (images) |
| **Infrastructure** | Red Hat OpenShift AI 3.3, KServe model serving, vLLM/vLLM-Omni inference |
| **MCP Transport** | Proper streamable-http (not REST wrappers) — production-grade |
| **KAgent Labels** | kagenti.io labels for Kubernetes-native agent discovery |

---

## If Something Goes Wrong

| Issue | Quick Fix |
|-------|-----------|
| Dashboard won't load | Check frontend pod: `oc get pods -n marketing-assistant-v2` |
| Generation takes too long | The Qwen Coder model can take 60-90s. SSE events show progress — just wait. |
| "Local mode" appears | K8s deploy failed — RBAC issue. Can still show the email + recipient flow. |
| Image gen fails | Non-fatal — falls back to CSS gradients. Landing page still generates. |
| 500 error | Check campaign-api logs: `oc logs deployment/campaign-api -n marketing-assistant-v2 --tail=10` |

---

## Architecture One-Liner

> "4 AI agents communicating via A2A protocol, accessing tools via MCP, orchestrated by LangGraph, running 3 open-source GPU models on Red Hat OpenShift AI — generating a complete marketing campaign in under 3 minutes."

---

## Sample Campaign Descriptions (for demo variety)

Use these when creating campaigns during the demo. Each pairs well with a different theme and audience.

### 1. Chinese New Year VIP Gala (Theme: Festive Red, Audience: Platinum members)
**Name:** `CNY VIP Gala`
**Description:** `Ring in the Year of the Snake with an exclusive celebration for our most distinguished guests. Five-star dining, private gaming salons, and world-class entertainment await. Limited to 100 invitations.`

### 2. Summer Luxury Escape (Theme: Luxury Gold, Audience: All VIP customers)
**Name:** `Summer Luxury Escape`
**Description:** `Escape to paradise with our premium summer package. Oceanview suites, infinity pool access, and complimentary spa treatments for an unforgettable retreat. Available June through August.`

### 3. Mid-Autumn Festival (Theme: Festive Red, Audience: Gold members)
**Name:** `Mid-Autumn Festival`
**Description:** `Celebrate the Mid-Autumn Festival under the Macau skyline. Exclusive mooncake tasting, lantern garden experience, and a VIP entertainment showcase. A night of tradition and elegance.`

### 4. New Member Welcome (Theme: Modern Black, Audience: New members)
**Name:** `Welcome Experience`
**Description:** `Your journey begins here. As a new member, enjoy a complimentary welcome package including dining credits, spa vouchers, and a private casino orientation with a personal host.`

### 5. High Roller Weekend (Theme: Classic Casino, Audience: Diamond members)
**Name:** `Diamond Weekend`
**Description:** `An invitation-only weekend for our most valued patrons. Private jet transfers, presidential suite, unlimited table access, and a dedicated concierge team. By invitation only.`

### 6. Wellness Retreat (Theme: Luxury Gold, Audience: High-spend customers)
**Name:** `Wellness Retreat`
**Description:** `Recharge with our curated wellness experience. Two nights in a luxury suite, daily spa treatments, private yoga sessions, and a Michelin-starred dining experience. Limited availability.`
