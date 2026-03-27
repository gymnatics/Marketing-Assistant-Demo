"""
Kubernetes/DevOps Agent - Builds and deploys campaigns to OpenShift.

Uses the Kubernetes Python client to interact with the cluster API directly,
avoiding the need for the oc CLI.
"""
import sys
import os
import base64
import io
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.state import CampaignState
from config import settings

# Kubernetes client imports
from kubernetes import client, config
from kubernetes.client.rest import ApiException


def get_k8s_clients():
    """Get Kubernetes API clients, using in-cluster config if available."""
    try:
        # Try in-cluster config first (when running in a pod)
        config.load_incluster_config()
        print("[K8s Agent] Using in-cluster configuration")
    except config.ConfigException:
        try:
            # Fall back to kubeconfig (local development)
            config.load_kube_config()
            print("[K8s Agent] Using kubeconfig")
        except config.ConfigException:
            print("[K8s Agent] Warning: No Kubernetes configuration found")
            return None, None, None
    
    core_v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    
    # For OpenShift routes, we need the custom objects API
    custom_api = client.CustomObjectsApi()
    
    return core_v1, apps_v1, custom_api


def sanitize_name(name: str) -> str:
    """Convert a string to a valid Kubernetes resource name."""
    sanitized = name.lower().replace(" ", "-").replace("_", "-")
    sanitized = "".join(c for c in sanitized if c.isalnum() or c == "-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    sanitized = sanitized.strip("-")
    return sanitized[:63]


def ensure_namespace_exists(core_v1: client.CoreV1Api, namespace: str) -> bool:
    """Ensure the target namespace exists."""
    try:
        core_v1.read_namespace(namespace)
        return True
    except ApiException as e:
        if e.status == 404:
            try:
                ns = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
                core_v1.create_namespace(ns)
                print(f"[K8s Agent] Created namespace: {namespace}")
                return True
            except ApiException as create_error:
                print(f"[K8s Agent] Failed to create namespace: {create_error}")
                return False
        print(f"[K8s Agent] Error checking namespace: {e}")
        return False


def create_configmap_from_html(
    core_v1: client.CoreV1Api,
    name: str,
    namespace: str,
    html_content: str
) -> bool:
    """Create a ConfigMap containing the HTML content."""
    configmap = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=name),
        data={"index.html": html_content}
    )
    
    # Also create nginx config to allow iframe embedding
    nginx_config_name = name.replace("-html", "-nginx-conf")
    nginx_config = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=nginx_config_name),
        data={
            "default.conf": """server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;
    
    # Allow iframe embedding from any origin
    add_header X-Frame-Options "" always;
    add_header Content-Security-Policy "" always;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
}
"""
        }
    )
    
    try:
        # Delete and create nginx config
        try:
            core_v1.delete_namespaced_config_map(nginx_config_name, namespace)
        except ApiException as e:
            if e.status != 404:
                raise
        core_v1.create_namespaced_config_map(namespace, nginx_config)
        print(f"[K8s Agent] Created nginx ConfigMap: {nginx_config_name}")
    except ApiException as e:
        print(f"[K8s Agent] Warning: Failed to create nginx config: {e}")
    
    try:
        # Try to delete existing configmap first
        try:
            core_v1.delete_namespaced_config_map(name, namespace)
            print(f"[K8s Agent] Deleted existing ConfigMap: {name}")
        except ApiException as e:
            if e.status != 404:
                raise
        
        # Create new configmap
        core_v1.create_namespaced_config_map(namespace, configmap)
        print(f"[K8s Agent] Created ConfigMap: {name}")
        return True
    except ApiException as e:
        print(f"[K8s Agent] Failed to create ConfigMap: {e}")
        return False


def deploy_nginx_with_html(
    apps_v1: client.AppsV1Api,
    deployment_name: str,
    namespace: str,
    configmap_name: str
) -> bool:
    """Deploy nginx serving the HTML from ConfigMap."""
    
    nginx_config_name = configmap_name.replace("-html", "-nginx-conf")
    
    deployment = client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=deployment_name,
            labels={"app": deployment_name, "type": "marketing-campaign"}
        ),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(
                match_labels={"app": deployment_name}
            ),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={"app": deployment_name}
                ),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name="nginx",
                            image="nginxinc/nginx-unprivileged:alpine",
                            ports=[client.V1ContainerPort(container_port=8080)],
                            volume_mounts=[
                                client.V1VolumeMount(
                                    name="html-content",
                                    mount_path="/usr/share/nginx/html",
                                    read_only=True
                                ),
                                client.V1VolumeMount(
                                    name="nginx-config",
                                    mount_path="/etc/nginx/conf.d",
                                    read_only=True
                                )
                            ],
                            resources=client.V1ResourceRequirements(
                                limits={"cpu": "100m", "memory": "128Mi"},
                                requests={"cpu": "50m", "memory": "64Mi"}
                            )
                        )
                    ],
                    volumes=[
                        client.V1Volume(
                            name="html-content",
                            config_map=client.V1ConfigMapVolumeSource(name=configmap_name)
                        ),
                        client.V1Volume(
                            name="nginx-config",
                            config_map=client.V1ConfigMapVolumeSource(name=nginx_config_name)
                        )
                    ]
                )
            )
        )
    )
    
    try:
        # Try to update existing deployment, or create new one
        try:
            apps_v1.replace_namespaced_deployment(deployment_name, namespace, deployment)
            print(f"[K8s Agent] Updated Deployment: {deployment_name}")
        except ApiException as e:
            if e.status == 404:
                apps_v1.create_namespaced_deployment(namespace, deployment)
                print(f"[K8s Agent] Created Deployment: {deployment_name}")
            else:
                raise
        return True
    except ApiException as e:
        print(f"[K8s Agent] Failed to create Deployment: {e}")
        return False


def create_service(
    core_v1: client.CoreV1Api,
    deployment_name: str,
    namespace: str
) -> bool:
    """Create a Service for the deployment."""
    
    service = client.V1Service(
        metadata=client.V1ObjectMeta(name=deployment_name),
        spec=client.V1ServiceSpec(
            selector={"app": deployment_name},
            ports=[client.V1ServicePort(port=8080, target_port=8080)],
            type="ClusterIP"
        )
    )
    
    try:
        try:
            core_v1.replace_namespaced_service(deployment_name, namespace, service)
            print(f"[K8s Agent] Updated Service: {deployment_name}")
        except ApiException as e:
            if e.status == 404:
                core_v1.create_namespaced_service(namespace, service)
                print(f"[K8s Agent] Created Service: {deployment_name}")
            else:
                raise
        return True
    except ApiException as e:
        print(f"[K8s Agent] Failed to create Service: {e}")
        return False


def create_route(
    custom_api: client.CustomObjectsApi,
    deployment_name: str,
    namespace: str,
    cluster_domain: str
) -> Optional[str]:
    """Create an OpenShift Route to expose the service externally."""
    
    route_host = f"{deployment_name}-{namespace}.{cluster_domain}"
    
    route = {
        "apiVersion": "route.openshift.io/v1",
        "kind": "Route",
        "metadata": {
            "name": deployment_name,
            "namespace": namespace
        },
        "spec": {
            "host": route_host,
            "to": {
                "kind": "Service",
                "name": deployment_name
            },
            "port": {
                "targetPort": 8080
            },
            "tls": {
                "termination": "edge",
                "insecureEdgeTerminationPolicy": "Redirect"
            }
        }
    }
    
    try:
        # Try to delete existing route first
        try:
            custom_api.delete_namespaced_custom_object(
                group="route.openshift.io",
                version="v1",
                namespace=namespace,
                plural="routes",
                name=deployment_name
            )
            print(f"[K8s Agent] Deleted existing Route: {deployment_name}")
        except ApiException as e:
            if e.status != 404:
                raise
        
        # Create new route
        custom_api.create_namespaced_custom_object(
            group="route.openshift.io",
            version="v1",
            namespace=namespace,
            plural="routes",
            body=route
        )
        print(f"[K8s Agent] Created Route: {deployment_name}")
        return f"https://{route_host}"
    except ApiException as e:
        print(f"[K8s Agent] Failed to create Route: {e}")
        return None


def generate_qr_code(url: str) -> str:
    """Generate a QR code for the URL and return as base64 data URI."""
    try:
        import qrcode
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        
        b64_data = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{b64_data}"
    except ImportError:
        print("[K8s Agent] qrcode library not installed, skipping QR generation")
        return ""


def deploy_to_dev(state: CampaignState) -> CampaignState:
    """Deploy the campaign to the dev namespace for preview."""
    
    core_v1, apps_v1, custom_api = get_k8s_clients()
    
    if not core_v1:
        state["error_message"] = "Kubernetes client not configured"
        state["current_step"] = "error"
        return state
    
    campaign_id = state.get("campaign_id", "campaign")
    deployment_name = sanitize_name(f"{campaign_id}-preview")
    configmap_name = f"{deployment_name}-html"
    namespace = settings.DEV_NAMESPACE
    
    print(f"[K8s Agent] Deploying to dev namespace: {namespace}")
    
    # Ensure namespace exists
    if not ensure_namespace_exists(core_v1, namespace):
        state["error_message"] = f"Failed to access namespace: {namespace}"
        state["current_step"] = "error"
        return state
    
    # Create ConfigMap with HTML
    if not create_configmap_from_html(core_v1, configmap_name, namespace, state["generated_html"]):
        state["error_message"] = "Failed to create ConfigMap"
        state["current_step"] = "error"
        return state
    
    # Deploy nginx
    if not deploy_nginx_with_html(apps_v1, deployment_name, namespace, configmap_name):
        state["error_message"] = "Failed to create Deployment"
        state["current_step"] = "error"
        return state
    
    # Create Service
    if not create_service(core_v1, deployment_name, namespace):
        state["error_message"] = "Failed to create Service"
        state["current_step"] = "error"
        return state
    
    # Create Route
    preview_url = create_route(custom_api, deployment_name, namespace, settings.CLUSTER_DOMAIN)
    if not preview_url:
        state["error_message"] = "Failed to create Route"
        state["current_step"] = "error"
        return state
    
    # Generate QR code
    qr_code = generate_qr_code(preview_url)
    
    # Update state
    state["deployment_name"] = deployment_name
    state["preview_url"] = preview_url
    state["preview_qr_code"] = qr_code
    state["current_step"] = "preview_ready"
    state["awaiting_approval"] = True
    
    state["messages"] = state.get("messages", []) + [{
        "role": "assistant",
        "agent": "k8s",
        "content": f"Campaign deployed to preview environment. URL: {preview_url}"
    }]
    
    print(f"[K8s Agent] Preview deployed successfully: {preview_url}")
    
    return state


def promote_to_production(state: CampaignState) -> CampaignState:
    """Promote the campaign from dev to production namespace."""
    
    core_v1, apps_v1, custom_api = get_k8s_clients()
    
    if not core_v1:
        state["error_message"] = "Kubernetes client not configured"
        state["current_step"] = "error"
        return state
    
    campaign_id = state.get("campaign_id", "campaign")
    deployment_name = sanitize_name(f"{campaign_id}")
    configmap_name = f"{deployment_name}-html"
    namespace = settings.PROD_NAMESPACE
    
    print(f"[K8s Agent] Promoting to production namespace: {namespace}")
    
    # Ensure namespace exists
    if not ensure_namespace_exists(core_v1, namespace):
        state["error_message"] = f"Failed to access namespace: {namespace}"
        state["current_step"] = "error"
        return state
    
    # Create ConfigMap with HTML
    if not create_configmap_from_html(core_v1, configmap_name, namespace, state["generated_html"]):
        state["error_message"] = "Failed to create ConfigMap in production"
        state["current_step"] = "error"
        return state
    
    # Deploy nginx
    if not deploy_nginx_with_html(apps_v1, deployment_name, namespace, configmap_name):
        state["error_message"] = "Failed to create Deployment in production"
        state["current_step"] = "error"
        return state
    
    # Create Service
    if not create_service(core_v1, deployment_name, namespace):
        state["error_message"] = "Failed to create Service in production"
        state["current_step"] = "error"
        return state
    
    # Create Route
    production_url = create_route(custom_api, deployment_name, namespace, settings.CLUSTER_DOMAIN)
    if not production_url:
        state["error_message"] = "Failed to create Route in production"
        state["current_step"] = "error"
        return state
    
    # Update state
    state["production_url"] = production_url
    state["current_step"] = "deployed_to_production"
    state["awaiting_approval"] = False
    
    state["messages"] = state.get("messages", []) + [{
        "role": "assistant",
        "agent": "k8s",
        "content": f"Campaign promoted to production! Live URL: {production_url}"
    }]
    
    print(f"[K8s Agent] Production deployment successful: {production_url}")
    
    return state


def k8s_agent(state: CampaignState, action: str = "deploy_preview") -> CampaignState:
    """
    K8s/DevOps Agent node for LangGraph workflow.
    
    Actions:
    - deploy_preview: Deploy to dev namespace
    - promote_production: Promote to production
    """
    
    if action == "deploy_preview":
        return deploy_to_dev(state)
    elif action == "promote_production":
        return promote_to_production(state)
    else:
        state["error_message"] = f"Unknown action: {action}"
        return state


# Wrapper functions for LangGraph nodes
def k8s_agent_deploy_preview(state: CampaignState) -> CampaignState:
    """LangGraph node: Deploy to preview environment."""
    return k8s_agent(state, action="deploy_preview")


def k8s_agent_promote_production(state: CampaignState) -> CampaignState:
    """LangGraph node: Promote to production."""
    return k8s_agent(state, action="promote_production")


# For testing
if __name__ == "__main__":
    from src.state import create_initial_state
    
    test_state = create_initial_state(
        campaign_name="Test Campaign",
        campaign_description="Test description",
    )
    test_state["generated_html"] = """<!DOCTYPE html>
<html>
<head><title>Test Campaign</title></head>
<body><h1>Test Campaign Page</h1><p>This is a test.</p></body>
</html>"""
    
    result = k8s_agent_deploy_preview(test_state)
    print(f"\nPreview URL: {result.get('preview_url', 'Not deployed')}")
    print(f"Error: {result.get('error_message', 'None')}")
