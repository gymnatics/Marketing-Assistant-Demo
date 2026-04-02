"""
Delivery Manager Agent - Pure business logic.

Generates marketing emails (EN/ZH) using Qwen3-32B-FP8-Dynamic and
deploys campaign landing pages to OpenShift via the Kubernetes Python client.
"""
import os
import json
import uuid
import httpx
from typing import List, Optional
from kubernetes import client, config
from kubernetes.client.rest import ApiException

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import (
    CustomerProfile,
    GenerateEmailInput,
    GenerateEmailOutput,
    DeployPreviewInput,
    DeployPreviewOutput,
    DeployProductionInput,
    DeployProductionOutput,
    SendEmailsInput,
    SendEmailsOutput,
)

LANG_MODEL_ENDPOINT = os.environ.get(
    "LANG_MODEL_ENDPOINT",
    "https://qwen3-32b-fp8-dynamic-0-marketing-assistant-demo.apps.cluster-qf44v.qf44v.sandbox543.opentlc.com/v1",
)
LANG_MODEL_NAME = os.environ.get("LANG_MODEL_NAME", "qwen3-32b-fp8-dynamic")
CAMPAIGN_API_URL = os.environ.get("CAMPAIGN_API_URL", "http://campaign-api:5000")
EVENT_HUB_URL = os.environ.get("EVENT_HUB_URL", "http://event-hub:5001")
CLUSTER_DOMAIN = os.environ.get(
    "CLUSTER_DOMAIN", "apps.cluster-qf44v.qf44v.sandbox543.opentlc.com"
)
DEV_NAMESPACE = os.environ.get("DEV_NAMESPACE", "0-marketing-assistant-demo-dev")
PROD_NAMESPACE = os.environ.get("PROD_NAMESPACE", "0-marketing-assistant-demo-prod")


MARKETING_SYSTEM_PROMPT = """You are a luxury casino marketing expert creating personalized email campaigns.

Generate email content in the following EXACT format:

---ENGLISH_SUBJECT---
[English email subject line here]

---ENGLISH_BODY---
[English email body as HTML fragment - see formatting rules below]

---CHINESE_SUBJECT---
[Chinese email subject line here]

---CHINESE_BODY---
[Chinese email body as HTML fragment - see formatting rules below]

## Email Body HTML Formatting Rules:
- Use ONLY inline HTML tags like <h1>, <h2>, <p>, <strong>, <em>, <a>, <br>
- Do NOT include <!DOCTYPE>, <html>, <head>, <body>, or <style> tags
- Do NOT wrap content in any document structure
- For the CTA button, use: <a href="URL" style="background-color:#C41E3A;color:#ffffff;padding:12px 24px;text-decoration:none;border-radius:5px;display:inline-block;font-weight:bold;">Button Text</a>

## Email Style Guidelines:
- Keep subject lines under 60 characters
- Use elegant, premium language
- Use EXACTLY `{{customer_name}}` as the greeting placeholder (the system replaces it per recipient)
- Use EXACTLY `{{campaign_link}}` as the CTA button href (personalized per recipient)
- Add a prominent call-to-action button that links to the ACTUAL campaign URL provided (NOT a placeholder)
- Sign off with the hotel/casino name

IMPORTANT: 
- The call-to-action button href MUST use the exact campaign URL provided in the prompt. Do NOT use placeholder text like "{{campaign_url}}" - use the actual URL.
- Mention that this is a personalized invitation — the landing page knows who they are.
- Add a line like "Your personalized experience awaits" or "A page crafted exclusively for you"."""


async def publish_event(
    campaign_id: str,
    event_type: str,
    agent: str,
    task: str,
    data: dict = None,
):
    """Publish event to Event Hub for UI updates."""
    try:
        async with httpx.AsyncClient() as http_client:
            await http_client.post(
                f"{EVENT_HUB_URL}/events/{campaign_id}/publish",
                json={
                    "event_type": event_type,
                    "agent": agent,
                    "task": task,
                    "data": data or {},
                },
                timeout=5.0,
            )
    except Exception as e:
        print(f"[Delivery Manager] Failed to publish event: {e}")


def parse_email_response(response: str) -> dict:
    """Parse the structured email response into components."""
    result = {
        "email_subject_en": "",
        "email_body_en": "",
        "email_subject_zh": "",
        "email_body_zh": "",
    }

    sections = {
        "---ENGLISH_SUBJECT---": "email_subject_en",
        "---ENGLISH_BODY---": "email_body_en",
        "---CHINESE_SUBJECT---": "email_subject_zh",
        "---CHINESE_BODY---": "email_body_zh",
    }

    current_section = None
    current_content: list[str] = []

    for line in response.split("\n"):
        line_stripped = line.strip()

        if line_stripped in sections:
            if current_section:
                result[current_section] = "\n".join(current_content).strip()
            current_section = sections[line_stripped]
            current_content = []
        elif current_section:
            current_content.append(line)

    if current_section:
        result[current_section] = "\n".join(current_content).strip()

    return result


async def generate_email_with_streaming(
    campaign_name: str,
    campaign_description: str,
    hotel_name: str,
    campaign_url: str,
    target_audience: str,
    start_date: str,
    end_date: str,
) -> dict:
    """Generate email content using streaming to avoid timeout."""

    date_info = ""
    if start_date and end_date:
        date_info = f"\n- **Campaign Period:** {start_date} to {end_date}"
    elif end_date:
        date_info = f"\n- **Offer Expires:** {end_date}"

    user_prompt = f"""Create a marketing email for the following campaign:

## Campaign Details:
- **Campaign Name:** {campaign_name}
- **Description:** {campaign_description}
- **Hotel/Casino:** {hotel_name}
- **Campaign Landing Page URL:** {campaign_url}
- **Target Audience:** {target_audience}{date_info}

## Requirements:
1. Create an enticing subject line that drives opens
2. Write an elegant email body with:
   - Personalized greeting using {{{{customer_name}}}} placeholder
   - CTA button href MUST be {{{{campaign_link}}}} (NOT the raw campaign URL)
   - Compelling description of the offer
   - Sense of exclusivity and urgency
   - Include the campaign dates ({start_date} to {end_date}) in the email body
   - A styled call-to-action button with href="{campaign_url}" (use this EXACT URL)
   - Professional sign-off from {hotel_name}
3. Use HTML formatting for the body (headers, paragraphs, button styling)
4. Provide both English and Chinese versions

CRITICAL: 
- The CTA button MUST link to: {campaign_url}
- Use the ACTUAL dates provided ({start_date} to {end_date}), NOT placeholders like [date]

Generate the email content now:"""

    url = f"{LANG_MODEL_ENDPOINT}/chat/completions"
    headers = {"Content-Type": "application/json"}

    payload = {
        "model": LANG_MODEL_NAME,
        "messages": [
            {"role": "system", "content": MARKETING_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 4000,
        "stream": True,
    }

    content = ""

    async with httpx.AsyncClient(timeout=180.0) as http_client:
        async with http_client.stream(
            "POST", url, json=payload, headers=headers
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                raise Exception(
                    f"Model API error: {response.status_code} - {error_text}"
                )

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            delta = chunk["choices"][0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                content += text
                    except json.JSONDecodeError:
                        continue

    return parse_email_response(content)


def init_k8s_client():
    """Initialize Kubernetes client."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        try:
            config.load_kube_config()
        except config.ConfigException:
            raise Exception("Could not configure Kubernetes client")


LANDING_IMAGE = os.environ.get(
    "LANDING_IMAGE", "quay.io/rh-ee-dayeo/marketing-assistant:campaign-landing"
)


def deploy_campaign_to_k8s(
    campaign_id: str, html_content: str, namespace: str, customers_json: str = "[]", campaign_json: str = "{}"
) -> str:
    """Deploy personalized campaign landing page to OpenShift using Express.js app."""
    init_k8s_client()

    core_v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    deployment_name = f"campaign-{campaign_id[:8]}-preview"

    data_configmap = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=f"{deployment_name}-data"),
        data={
            "template.html": html_content,
            "customers.json": customers_json,
            "campaign.json": campaign_json,
        },
    )

    try:
        core_v1.create_namespaced_config_map(namespace=namespace, body=data_configmap)
    except ApiException as e:
        if e.status == 409:
            core_v1.replace_namespaced_config_map(
                name=f"{deployment_name}-data",
                namespace=namespace,
                body=data_configmap,
            )
        else:
            raise

    deployment = client.V1Deployment(
        metadata=client.V1ObjectMeta(name=deployment_name),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(
                match_labels={"app": deployment_name}
            ),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": deployment_name}),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name="landing",
                            image=LANDING_IMAGE,
                            image_pull_policy="Always",
                            ports=[client.V1ContainerPort(container_port=8080)],
                            env=[
                                client.V1EnvVar(name="MONGODB_MCP_URL", value=os.environ.get("MONGODB_MCP_URL", "http://mongodb-mcp.marketing-assistant-v2.svc:8090")),
                            ],
                            volume_mounts=[
                                client.V1VolumeMount(
                                    name="data",
                                    mount_path="/data",
                                ),
                            ],
                        )
                    ],
                    volumes=[
                        client.V1Volume(
                            name="data",
                            config_map=client.V1ConfigMapVolumeSource(
                                name=f"{deployment_name}-data"
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )

    try:
        apps_v1.create_namespaced_deployment(namespace=namespace, body=deployment)
    except ApiException as e:
        if e.status == 409:
            apps_v1.replace_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=deployment,
            )
        else:
            raise

    service = client.V1Service(
        metadata=client.V1ObjectMeta(name=deployment_name),
        spec=client.V1ServiceSpec(
            selector={"app": deployment_name},
            ports=[client.V1ServicePort(port=80, target_port=8080)],
        ),
    )

    try:
        core_v1.create_namespaced_service(namespace=namespace, body=service)
    except ApiException as e:
        if e.status != 409:
            raise

    route_url = f"https://{deployment_name}-{namespace}.{CLUSTER_DOMAIN}/"

    try:
        custom_api = client.CustomObjectsApi()
        route = {
            "apiVersion": "route.openshift.io/v1",
            "kind": "Route",
            "metadata": {"name": deployment_name},
            "spec": {
                "to": {
                    "kind": "Service",
                    "name": deployment_name,
                },
                "port": {"targetPort": 8080},
                "tls": {"termination": "edge"},
            },
        }

        try:
            custom_api.create_namespaced_custom_object(
                group="route.openshift.io",
                version="v1",
                namespace=namespace,
                plural="routes",
                body=route,
            )
        except ApiException as e:
            if e.status != 409:
                raise
    except Exception as e:
        print(f"[Delivery Manager] Route creation failed (may not be OpenShift): {e}")

    return route_url


class DeliveryManagerAgent:
    """Pure business logic for the Delivery Manager agent."""

    async def generate_email(self, params: dict) -> dict:
        """Generate marketing email content in English and Chinese."""
        validated = GenerateEmailInput(**params)
        campaign_id = params.get("campaign_id", str(uuid.uuid4())[:8])

        await publish_event(
            campaign_id=campaign_id,
            event_type="agent_started",
            agent="Delivery Manager",
            task="Writing personalized emails...",
        )

        try:
            email_data = await generate_email_with_streaming(
                campaign_name=validated.campaign_name,
                campaign_description=validated.campaign_description,
                hotel_name=validated.hotel_name,
                campaign_url=validated.campaign_url,
                target_audience=validated.target_audience,
                start_date=validated.start_date,
                end_date=validated.end_date,
            )

            result = GenerateEmailOutput(
                email_subject_en=email_data.get("email_subject_en", ""),
                email_body_en=email_data.get("email_body_en", ""),
                email_subject_zh=email_data.get("email_subject_zh", ""),
                email_body_zh=email_data.get("email_body_zh", ""),
                status="success",
            )

            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_completed",
                agent="Delivery Manager",
                task="Email content ready",
            )

            return result.model_dump()

        except Exception as e:
            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_error",
                agent="Delivery Manager",
                task="Email writing failed",
                data={"error": str(e)},
            )
            return GenerateEmailOutput(
                email_subject_en="",
                email_body_en="",
                email_subject_zh="",
                email_body_zh="",
                status="error",
                error=str(e),
            ).model_dump()

    async def deploy_preview(self, params: dict) -> dict:
        """Deploy campaign landing page to the preview (dev) environment."""
        validated = DeployPreviewInput(**params)

        await publish_event(
            campaign_id=validated.campaign_id,
            event_type="agent_started",
            agent="Delivery Manager",
            task="Publishing preview...",
        )

        try:
            customers_json = params.get("customers_json", "[]")
            campaign_json = params.get("campaign_json", "{}")
            preview_url = deploy_campaign_to_k8s(
                campaign_id=validated.campaign_id,
                html_content=validated.html_content,
                namespace=validated.namespace or DEV_NAMESPACE,
                customers_json=customers_json,
                campaign_json=campaign_json,
            )

            result = DeployPreviewOutput(preview_url=preview_url, status="success")

            await publish_event(
                campaign_id=validated.campaign_id,
                event_type="agent_completed",
                agent="Delivery Manager",
                task="Preview published",
                data={"preview_url": preview_url},
            )

            return result.model_dump()

        except Exception as e:
            await publish_event(
                campaign_id=validated.campaign_id,
                event_type="agent_error",
                agent="Delivery Manager",
                task="Preview publishing failed",
                data={"error": str(e)},
            )
            return DeployPreviewOutput(
                preview_url="",
                status="error",
                error=str(e),
            ).model_dump()

    async def deploy_production(self, params: dict) -> dict:
        """Deploy campaign landing page to the production environment."""
        validated = DeployProductionInput(**params)

        await publish_event(
            campaign_id=validated.campaign_id,
            event_type="agent_started",
            agent="Delivery Manager",
            task="Going live...",
        )

        try:
            customers_json = params.get("customers_json", "[]")
            campaign_json = params.get("campaign_json", "{}")
            production_url = deploy_campaign_to_k8s(
                campaign_id=validated.campaign_id,
                html_content=validated.html_content,
                namespace=validated.namespace or PROD_NAMESPACE,
                customers_json=customers_json,
                campaign_json=campaign_json,
            )

            result = DeployProductionOutput(
                production_url=production_url, status="success"
            )

            await publish_event(
                campaign_id=validated.campaign_id,
                event_type="agent_completed",
                agent="Delivery Manager",
                task="Campaign is live!",
                data={"production_url": production_url},
            )

            return result.model_dump()

        except Exception as e:
            await publish_event(
                campaign_id=validated.campaign_id,
                event_type="agent_error",
                agent="Delivery Manager",
                task="Live deployment failed",
                data={"error": str(e)},
            )
            return DeployProductionOutput(
                production_url="",
                status="error",
                error=str(e),
            ).model_dump()

    async def send_emails(self, params: dict) -> dict:
        """Send marketing emails to customer list (simulated)."""
        validated = SendEmailsInput(**params)

        await publish_event(
            campaign_id=validated.campaign_id,
            event_type="agent_started",
            agent="Delivery Manager",
            task=f"Delivering to {len(validated.customers)} recipients...",
        )

        sent_count = len(validated.customers)

        for customer in validated.customers:
            print(f"[Delivery Manager] SIMULATED: Sending email to {customer.email}")

        # Send personalized emails to fake inbox for each customer
        import datetime as _dt
        for customer in validated.customers[:5]:
            try:
                name = customer.name_en or customer.name
                campaign_url = params.get("campaign_url", "")
                personalized_link = f"{campaign_url}?c={customer.customer_id}" if campaign_url and customer.customer_id else campaign_url
                body = validated.email_body_en.replace("{{customer_name}}", name).replace("{{CUSTOMER_NAME}}", name).replace("{{campaign_link}}", personalized_link).replace("{{CAMPAIGN_LINK}}", personalized_link)
                subject = validated.email_subject_en.replace("{{customer_name}}", name).replace("{{CUSTOMER_NAME}}", name).replace("{{campaign_link}}", personalized_link).replace("{{CAMPAIGN_LINK}}", personalized_link)
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(f"{CAMPAIGN_API_URL}/api/inbox", json={
                        "from_name": "Simon Casino Resort",
                        "from_email": "campaigns@simoncasino.com",
                        "to_name": name,
                        "to_email": customer.email,
                        "subject": subject,
                        "body": body,
                        "date": _dt.datetime.utcnow().isoformat(),
                        "customer_id": customer.customer_id,
                        "campaign_url": personalized_link,
                    })
            except Exception as e:
                print(f"[Delivery Manager] Inbox POST failed for {customer.email}: {e}")

        result = SendEmailsOutput(sent_count=sent_count, status="success")

        await publish_event(
            campaign_id=validated.campaign_id,
            event_type="agent_completed",
            agent="Delivery Manager",
            task=f"Successfully sent to {sent_count} recipients",
            data={"sent_count": sent_count},
        )

        return result.model_dump()
