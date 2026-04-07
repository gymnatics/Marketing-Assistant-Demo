import json
import os
import sys
from typing import Any, Mapping

import mlflow

_initialized: bool = False

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

        mlflow.langchain.autolog()

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
