#!/bin/bash
################################################################################
# Setup Models for Marketing Assistant Demo
#
# One-command script that:
# 1. Sets up MinIO model storage (if not already done)
# 2. Downloads all 3 models from HuggingFace
# 3. Serves all 3 models via KServe
#
# Uses the RHOAI-Toolkit scripts from Openshift-installation repo.
#
# Usage:
#   ./setup-models.sh                    # Full setup (storage + download + serve)
#   ./setup-models.sh --serve-only       # Skip storage/download, just serve
#   ./setup-models.sh --download-only    # Skip serve, just storage + download
#
# Prerequisites:
#   - oc logged in to cluster
#   - RHOAI installed with GPU nodes available
#   - Openshift-installation repo at $TOOLKIT_DIR
################################################################################

set -e

# ─── Configuration ────────────────────────────────────────────────────────────

TOOLKIT_DIR="${TOOLKIT_DIR:-/Users/dayeo/Openshift-installation}"
STORAGE_NS="${STORAGE_NS:-model-storage}"
MODEL_NS="${MODEL_NS:-0-marketing-assistant-demo}"
BUCKET="models"
STORAGE_SIZE="300Gi"

# Models to deploy
MODELS=(
    "RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic"
    "RedHatAI/Qwen3-32B-FP8-dynamic"
    "black-forest-labs/FLUX.2-klein-4B"
)

# Serving configs: name|model_path|runtime|extra_args
SERVE_CONFIGS=(
    "qwen25-coder|RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic|vllm|--max-model-len 16384 --gpu-memory-utilization 0.95 --enable-auto-tool-choice --tool-call-parser hermes"
    "qwen3|RedHatAI/Qwen3-32B-FP8-dynamic|vllm|--dtype auto --max-model-len 16000 --gpu-memory-utilization 0.90 --enable-auto-tool-choice --tool-call-parser hermes"
    "flux2-klein|black-forest-labs/FLUX.2-klein-4B|omni|--gpu-memory-utilization 0.90"
)

# ─── Parse args ───────────────────────────────────────────────────────────────

SERVE_ONLY=false
DOWNLOAD_ONLY=false
for arg in "$@"; do
    case $arg in
        --serve-only) SERVE_ONLY=true ;;
        --download-only) DOWNLOAD_ONLY=true ;;
        --namespace=*) MODEL_NS="${arg#*=}" ;;
        --storage-ns=*) STORAGE_NS="${arg#*=}" ;;
        --toolkit=*) TOOLKIT_DIR="${arg#*=}" ;;
        --hf-token=*) export HF_TOKEN="${arg#*=}" ;;
        --help|-h)
            head -20 "$0" | grep "^#" | sed 's/^# \?//'
            exit 0
            ;;
    esac
done

# ─── Validation ───────────────────────────────────────────────────────────────

if ! oc whoami &>/dev/null; then
    echo "Error: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

if [ ! -d "$TOOLKIT_DIR/scripts" ]; then
    echo "Error: RHOAI-Toolkit not found at $TOOLKIT_DIR"
    echo "Set TOOLKIT_DIR to the Openshift-installation repo path."
    exit 1
fi

# HuggingFace token (for faster downloads and gated models)
if [ -z "${HF_TOKEN:-}" ]; then
    echo ""
    echo "HuggingFace token speeds up downloads and is required for gated models."
    read -p "Enter HF_TOKEN (or press Enter to skip): " HF_TOKEN_INPUT
    if [ -n "$HF_TOKEN_INPUT" ]; then
        export HF_TOKEN="$HF_TOKEN_INPUT"
        echo "  HF_TOKEN set."
    else
        echo "  Skipping (unauthenticated, slower downloads)."
    fi
else
    echo "HF_TOKEN already set."
fi

echo "=========================================="
echo "Marketing Assistant — Model Setup"
echo "=========================================="
echo "Cluster:     $(oc whoami --show-server 2>/dev/null | sed 's|https://api\.||; s|:6443||')"
echo "Storage NS:  $STORAGE_NS"
echo "Model NS:    $MODEL_NS"
echo "Toolkit:     $TOOLKIT_DIR"
echo ""

# ─── Per-model download function ──────────────────────────────────────────────
# Downloads ONE model at a time via a dedicated K8s Job using huggingface_hub
# snapshot_download. Each model gets its own job so timeouts and retries are
# isolated — no more "one stalled model blocks everything".

_download_model() {
    local MODEL="$1"
    local NS="$2"
    local BUCKET="$3"
    local S3_USER="$4"
    local S3_PASS="$5"

    local JOB_NAME="download-$(echo "$MODEL" | tr '/' '-' | tr '[:upper:]' '[:lower:]' | cut -c1-50)"
    oc delete job "$JOB_NAME" -n "$NS" 2>/dev/null || true

    local HF_TOKEN_ENV=""
    if [ -n "${HF_TOKEN:-}" ]; then
        HF_TOKEN_ENV="- name: HF_TOKEN
          value: \"${HF_TOKEN}\""
    fi

    cat <<EOFYAML | oc apply -n "$NS" -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 3600
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: downloader
        image: registry.access.redhat.com/ubi9/python-311:latest
        resources:
          requests:
            memory: "2Gi"
            cpu: "1"
          limits:
            memory: "4Gi"
            cpu: "2"
        env:
        - name: AWS_ACCESS_KEY_ID
          value: "${S3_USER}"
        - name: AWS_SECRET_ACCESS_KEY
          value: "${S3_PASS}"
        ${HF_TOKEN_ENV}
        command: ["/bin/bash", "-c"]
        args:
        - |
          set -e
          pip install -q --upgrade huggingface_hub awscli
          export PATH="\$PATH:/opt/app-root/src/.local/bin"
          S3_ENDPOINT="http://minio.${NS}.svc:9000"

          MODEL="${MODEL}"
          BUCKET="${BUCKET}"
          LOCAL_DIR="/tmp/models/\$MODEL"

          # Check if already in S3
          if aws --endpoint-url "\$S3_ENDPOINT" s3 ls "s3://\${BUCKET}/\${MODEL}/" >/dev/null 2>&1; then
            FILE_COUNT=\$(aws --endpoint-url "\$S3_ENDPOINT" s3 ls "s3://\${BUCKET}/\${MODEL}/" --recursive 2>/dev/null | wc -l)
            echo "Found \$FILE_COUNT existing files in S3 for \$MODEL"
          fi

          echo "Downloading \$MODEL from HuggingFace..."
          python3 -c "
          from huggingface_hub import snapshot_download
          snapshot_download(
              '\$MODEL',
              local_dir='\$LOCAL_DIR',
              max_workers=2,
          )
          print('Download complete!')
          "

          rm -rf "\$LOCAL_DIR/.cache"

          echo "Syncing to S3..."
          aws --endpoint-url "\$S3_ENDPOINT" s3 sync "\$LOCAL_DIR" "s3://\${BUCKET}/\${MODEL}/"

          rm -rf "\$LOCAL_DIR"
          echo "Done: \$MODEL synced to s3://\${BUCKET}/\${MODEL}/"
EOFYAML

    echo "  Job '${JOB_NAME}' created. Monitoring progress..."
    echo ""

    # Monitor the job
    local ELAPSED=0
    local TIMEOUT=3600
    while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
        sleep 15
        ELAPSED=$((ELAPSED + 15))

        local STATUS=$(oc get job "$JOB_NAME" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null)
        local FAILED=$(oc get job "$JOB_NAME" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null)

        if [ "$STATUS" = "True" ]; then
            echo "  Download complete! (${ELAPSED}s)"
            oc logs -n "$NS" -l "job-name=${JOB_NAME}" --tail=5 2>/dev/null
            return 0
        fi

        if [ "$FAILED" = "True" ]; then
            echo "  Download FAILED. Logs:"
            oc logs -n "$NS" -l "job-name=${JOB_NAME}" --tail=20 2>/dev/null
            return 1
        fi

        # Show progress every 30s (from the active pod only)
        if [ $((ELAPSED % 30)) -eq 0 ]; then
            local ACTIVE_POD=$(oc get pods -n "$NS" -l "job-name=${JOB_NAME}" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
            if [ -n "$ACTIVE_POD" ]; then
                local LAST_LOG=$(oc logs -n "$NS" "$ACTIVE_POD" --tail=1 2>/dev/null | head -1)
            else
                local LAST_LOG="(waiting for pod)"
            fi
            echo "  [${ELAPSED}s] ${LAST_LOG}"
        fi
    done

    echo "  WARNING: Download timed out after ${TIMEOUT}s."
    echo "  Check logs: oc logs -n $NS -l job-name=${JOB_NAME}"
    echo "  The job may still be running — it will auto-retry up to 3 times."
    return 1
}

# ─── Interactive menu ─────────────────────────────────────────────────────────

if [ "$SERVE_ONLY" = "false" ] && [ "$DOWNLOAD_ONLY" = "false" ]; then
    echo "What would you like to do?"
    echo "  (1) Full setup: MinIO + Download models + Serve models"
    echo "  (2) Download models only (MinIO must already exist)"
    echo "  (3) Serve models only (models must already be downloaded)"
    echo "  (4) Check status (show what's already done)"
    read -p "Choose [1/2/3/4]: " SETUP_CHOICE
    SETUP_CHOICE=${SETUP_CHOICE:-1}

    case "$SETUP_CHOICE" in
        2) SERVE_ONLY=false; DOWNLOAD_ONLY=true ;;
        3) SERVE_ONLY=true; DOWNLOAD_ONLY=false ;;
        4)
            echo ""
            echo "=== Status ==="
            MINIO_POD=$(oc exec -n "$STORAGE_NS" deploy/minio -- echo "ok" 2>/dev/null && echo "running" || echo "")
            echo "MinIO: ${MINIO_POD:+running}${MINIO_POD:-not found}"
            if [ -n "$MINIO_POD" ]; then
                MINIO_POD_NAME=$(oc get pods -n "$STORAGE_NS" -l app=minio -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
                for MODEL in "${MODELS[@]}"; do
                    SHORT=$(basename "$MODEL")
                    FC=$(oc exec "$MINIO_POD_NAME" -n "$STORAGE_NS" -- sh -c "ls /data/$BUCKET/$MODEL/ 2>/dev/null | wc -l" 2>/dev/null || echo "0")
                    echo "  $SHORT: ${FC} files"
                done
            fi
            echo ""
            echo "InferenceServices in $MODEL_NS:"
            oc get inferenceservice -n "$MODEL_NS" --no-headers 2>/dev/null | grep -vE "guardrails|prompt-injection" || echo "  None"
            echo ""
            exit 0
            ;;
    esac
fi

# ─── Step 1: Setup MinIO storage ─────────────────────────────────────────────

if [ "$SERVE_ONLY" = "false" ]; then
    echo ""
    echo "--- Step 1: Model Storage (MinIO) ---"
    echo ""

    MINIO_EXISTS=$(oc get deployment minio -n "$STORAGE_NS" --no-headers 2>/dev/null | wc -l | tr -dc '0-9')
    if [ "${MINIO_EXISTS:-0}" -ge 1 ]; then
        echo "MinIO already running in $STORAGE_NS — skipping setup."
    else
        echo "Setting up MinIO in $STORAGE_NS..."
        "$TOOLKIT_DIR/scripts/setup-model-storage.sh" \
            -n "$STORAGE_NS" \
            -b "$BUCKET" \
            --storage-size "$STORAGE_SIZE" \
            --minio-user minio \
            --minio-password minio123 \
            --data-connection-ns "$STORAGE_NS"
        # Also create data connection in the app namespace (for model serving)
        if [ "$MODEL_NS" != "$STORAGE_NS" ]; then
            echo "  Creating data connection in app namespace ($MODEL_NS)..."
            MINIO_ENDPOINT="http://minio.${STORAGE_NS}.svc:9000"
            for DC_NAME in aws-connection-minio aws-connection-my-storage; do
                oc create secret generic "$DC_NAME" -n "$MODEL_NS" \
                    --from-literal=AWS_ACCESS_KEY_ID=minio \
                    --from-literal=AWS_SECRET_ACCESS_KEY=minio123 \
                    --from-literal=AWS_S3_ENDPOINT="$MINIO_ENDPOINT" \
                    --from-literal=AWS_S3_BUCKET="$BUCKET" \
                    --from-literal=AWS_DEFAULT_REGION=us-east-1 \
                    --dry-run=client -o yaml | oc apply -f - 2>/dev/null
            done
        fi
    fi
    echo ""

    # ─── Step 2: Download models ──────────────────────────────────────────────

    if [ "$DOWNLOAD_ONLY" = "false" ]; then
        # Not download-only means full setup -- ask before downloading
        :
    fi

    echo "--- Step 2: Download Models ---"
    echo ""

    MINIO_POD_NAME=$(oc get pods -n "$STORAGE_NS" -l app=minio -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

    # Read MinIO credentials from the secret (matches what setup-model-storage.sh created)
    MINIO_USER=$(oc get secret minio -n "$STORAGE_NS" -o jsonpath='{.data.MINIO_ROOT_USER}' 2>/dev/null | base64 -d 2>/dev/null || echo "minio")
    MINIO_PASS=$(oc get secret minio -n "$STORAGE_NS" -o jsonpath='{.data.MINIO_ROOT_PASSWORD}' 2>/dev/null | base64 -d 2>/dev/null || echo "minio123")

    for MODEL in "${MODELS[@]}"; do
        MODEL_SHORT=$(basename "$MODEL")
        echo "Checking $MODEL_SHORT..."

        # Check if model already exists in MinIO
        if [ -n "$MINIO_POD_NAME" ]; then
            FC=$(oc exec "$MINIO_POD_NAME" -n "$STORAGE_NS" -- sh -c "ls /data/$BUCKET/$MODEL/ 2>/dev/null | wc -l" 2>/dev/null || echo "0")
            FC=$(echo "$FC" | tr -dc '0-9')
            if [ "${FC:-0}" -gt 0 ]; then
                echo "  Already downloaded ($FC files)."
                read -p "  Re-download? (y/N): " REDOWNLOAD
                if [ "$REDOWNLOAD" != "y" ] && [ "$REDOWNLOAD" != "Y" ]; then
                    echo "  Skipping."
                    continue
                fi
            fi
        fi

        echo "  Downloading $MODEL (dedicated job)..."
        _download_model "$MODEL" "$STORAGE_NS" "$BUCKET" "$MINIO_USER" "$MINIO_PASS"
        echo ""
    done
fi

# ─── Step 3: Serve models ────────────────────────────────────────────────────

if [ "$DOWNLOAD_ONLY" = "false" ]; then
    echo "--- Step 3: Serve Models ---"
    echo ""

    for CONFIG in "${SERVE_CONFIGS[@]}"; do
        IFS='|' read -r NAME MODEL_PATH RUNTIME EXTRA_ARGS <<< "$CONFIG"

        # Check if already serving
        ISVC_EXISTS=$(oc get inferenceservice -n "$MODEL_NS" --no-headers 2>/dev/null | grep -ci "$NAME" || true)
        if [ "${ISVC_EXISTS:-0}" -ge 1 ]; then
            echo "$NAME: Already serving — skipping."
            continue
        fi

        echo "Serving $NAME ($RUNTIME)..."
        if [ "$RUNTIME" = "omni" ]; then
            NAMESPACE="$MODEL_NS" RUNTIME=omni \
                "$TOOLKIT_DIR/scripts/serve-model.sh" s3 "$NAME" "$MODEL_PATH" "$EXTRA_ARGS" || echo "  (serve script returned non-zero — model may still be starting, continuing...)"
        else
            NAMESPACE="$MODEL_NS" \
                "$TOOLKIT_DIR/scripts/serve-model.sh" s3 "$NAME" "$MODEL_PATH" "$EXTRA_ARGS" || echo "  (serve script returned non-zero — model may still be starting, continuing...)"
        fi
        echo ""
    done

    echo ""
    echo "--- Waiting for models to be ready ---"
    for CONFIG in "${SERVE_CONFIGS[@]}"; do
        NAME="${CONFIG%%|*}"
        echo -n "  $NAME: "
        for i in $(seq 1 60); do
            READY=$(oc get inferenceservice -n "$MODEL_NS" --no-headers 2>/dev/null | grep "$NAME" | awk '{print $3}')
            if [ "$READY" = "True" ]; then
                echo "READY"
                break
            fi
            sleep 10
            echo -n "."
        done
        if [ "$READY" != "True" ]; then
            echo "NOT READY (may need more time)"
        fi
    done
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "=========================================="
echo "Model Setup Complete"
echo "=========================================="
echo ""
echo "InferenceServices:"
oc get inferenceservice -n "$MODEL_NS" --no-headers 2>/dev/null | grep -vE "guardrails|prompt-injection" | while read -r line; do
    echo "  $line"
done
echo ""
echo "Routes:"
for CONFIG in "${SERVE_CONFIGS[@]}"; do
    NAME="${CONFIG%%|*}"
    ROUTE=$(oc get route "$NAME" -n "$MODEL_NS" -o jsonpath='{.spec.host}' 2>/dev/null || echo "no-route")
    echo "  $NAME: https://$ROUTE/v1"
done
echo ""
echo "Next: run ./deploy.sh to deploy the app (models will be auto-detected)."
