import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping
from contextlib import nullcontext

import mlflow
from mlflow.tracing import set_tracing_context_from_http_request_headers

_initialized: bool = False

_SPIFFE_JWT_PATH = Path("/opt/jwt_svid.token")
_SPIFFE_X509_PATH = Path("/opt/svid.pem")

def ensure_mlflow_initialized() -> None:
    """Set tracking URI and active experiment once per process."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if not uri:
        return
    
    try:
        
        mlflow.set_tracking_uri(uri)
        name = (os.environ.get("MLFLOW_EXPERIMENT_NAME") or "default").strip() or "default"
        mlflow.set_experiment(name)

        try:
            mlflow.openai.autolog()
        except Exception:
            pass

        try:
            import langchain
            mlflow.langchain.autolog(run_tracer_inline=True)
        except (ImportError, Exception):
            pass
                
    except Exception as e:
        print(f"[mlflow_bootstrap] MLflow init failed ({e}); tracing may be disabled.", file=sys.stderr)

def update_trace_session(metadata: Mapping[str, Any]) -> None:
    """Attach session / campaign context to the active trace (inside @mlflow.trace)."""
    try:
        mlflow.update_current_trace(metadata=dict(metadata))
    except Exception:
        # No active trace or tracing unavailable — safe to ignore.
        pass

# def debug_session_log(
#     hypothesis_id: str,
#     location: str,
#     message: str,
#     data: dict[str, Any] | None = None,
# ) -> None:
#     """Lightweight structured log for agent / executor instrumentation regions."""
#     payload = {
#         "hypothesisId": hypothesis_id,
#         "location": location,
#         "message": message,
#         "data": data or {},
#         "sessionId": "debug-session",
#         "runId": "pre-fix",
#     }
#     print(json.dumps(payload, default=str), file=sys.stderr, flush=True)

def tag_trace_with_spiffe() -> None:
    """Tag the most recent MLflow trace with SPIFFE workload identity metadata.

    Reads the JWT SVID written by the spiffe-helper sidecar (KAgenti AuthBridge).
    No-ops gracefully when SVID files don't exist (non-KAgenti deployments).
    """
    try:
        if not _SPIFFE_JWT_PATH.exists():
            return

        jwt_token = _SPIFFE_JWT_PATH.read_text().strip()
        if not jwt_token:
            return

        # Decode JWT payload (second segment) without verification — it's a local file
        parts = jwt_token.split(".")
        if len(parts) < 2:
            return
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))

        tags: dict[str, str] = {}
        if "sub" in claims:
            tags["spiffe.id"] = str(claims["sub"])
        if "aud" in claims:
            tags["spiffe.audience"] = str(claims["aud"])
        if "iss" in claims:
            tags["spiffe.issuer"] = str(claims["iss"])
        if "exp" in claims:
            tags["spiffe.expiry"] = str(claims["exp"])

        # Truncated token/cert for reference (not full secrets)
        tags["spiffe.jwt_svid"] = jwt_token[:80]
        if _SPIFFE_X509_PATH.exists():
            tags["spiffe.x509_svid"] = _SPIFFE_X509_PATH.read_text()[:120]

        if tags:
            mlflow.update_current_trace(tags=tags)

    except Exception:
        pass


def set_safe_tracing_context(headers):
    if headers and "traceparent" in headers:
        return set_tracing_context_from_http_request_headers(headers)
    return nullcontext()