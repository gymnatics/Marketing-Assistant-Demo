"""Utilities for resolving model names from vLLM-compatible endpoints."""
import os
import httpx


def resolve_model_name(endpoint_env: str, name_env: str, default_name: str = "") -> str:
    """Resolve the served model name, querying the endpoint if needed.

    Priority:
    1. Explicit env var (e.g. CODE_MODEL_NAME) if set and non-empty
    2. Auto-detect from the /v1/models endpoint (works with any vLLM/OpenAI-compatible server)
    3. Fallback default
    """
    name = os.environ.get(name_env, "").strip()
    if name:
        return name

    endpoint = os.environ.get(endpoint_env, "").strip()
    if endpoint:
        try:
            url = endpoint.rstrip("/")
            if not url.endswith("/v1"):
                url = url.rstrip("/") + "/v1"
            resp = httpx.get(f"{url}/models", timeout=10.0, verify=False)
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                if models:
                    detected = models[0]["id"]
                    print(f"[model_utils] Auto-detected model name from {endpoint_env}: {detected}")
                    return detected
        except Exception as e:
            print(f"[model_utils] Could not auto-detect model from {endpoint_env}: {e}")

    if default_name:
        print(f"[model_utils] Using default model name: {default_name}")
    return default_name
