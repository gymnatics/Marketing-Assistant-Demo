#!/usr/bin/env bash
set -euo pipefail

# Usage:
# ./patch-notebook-envfrom.sh <namespace> <notebook-name> <configmap-name> <secret-name> [container-name]
#
# Example:
# ./patch-notebook-envfrom.sh marketing-assistant-v2 eval my-config my-secret eval
#
# What it does:
# - Adds BOTH ConfigMap + Secret to container envFrom
# - Preserves existing envFrom entries
# - Avoids duplicates
# - Restarts notebook StatefulSet

NAMESPACE="${1:?namespace required}"
NOTEBOOK="${2:?notebook name required}"
CONFIGMAP="${3:?configmap name required}"
SECRET="${4:?secret name required}"
CONTAINER="${5:-$NOTEBOOK}"

command -v oc >/dev/null || { echo "oc required"; exit 1; }
command -v jq >/dev/null || { echo "jq required"; exit 1; }

echo "Finding container index: $CONTAINER"

INDEX=$(
oc get notebook "$NOTEBOOK" -n "$NAMESPACE" -o json \
| jq --arg c "$CONTAINER" '
.spec.template.spec.containers
| map(.name == $c)
| index(true)
'
)

if [[ "$INDEX" == "null" ]]; then
  echo "Container $CONTAINER not found"
  exit 1
fi

echo "Reading existing envFrom..."

EXISTING_ENVFROM=$(
oc get notebook "$NOTEBOOK" -n "$NAMESPACE" -o json \
| jq --argjson idx "$INDEX" '
.spec.template.spec.containers[$idx].envFrom // []
'
)

NEW_ENVFROM="$EXISTING_ENVFROM"

# Add ConfigMap if missing
HAS_CM=$(echo "$NEW_ENVFROM" | jq --arg n "$CONFIGMAP" '
map(select(.configMapRef.name == $n)) | length
')

if [[ "$HAS_CM" -eq 0 ]]; then
  NEW_ENVFROM=$(
    echo "$NEW_ENVFROM" | jq --arg n "$CONFIGMAP" '
    . + [
      {
        configMapRef: {
          name: $n
        }
      }
    ]'
  )
else
  echo "ConfigMap already present: $CONFIGMAP"
fi

# Add Secret if missing
HAS_SECRET=$(echo "$NEW_ENVFROM" | jq --arg n "$SECRET" '
map(select(.secretRef.name == $n)) | length
')

if [[ "$HAS_SECRET" -eq 0 ]]; then
  NEW_ENVFROM=$(
    echo "$NEW_ENVFROM" | jq --arg n "$SECRET" '
    . + [
      {
        secretRef: {
          name: $n
        }
      }
    ]'
  )
else
  echo "Secret already present: $SECRET"
fi

PATCH=$(
jq -n \
  --arg cname "$CONTAINER" \
  --argjson envfrom "$NEW_ENVFROM" '
{
  spec: {
    template: {
      spec: {
        containers: [
          {
            name: $cname,
            envFrom: $envfrom
          }
        ]
      }
    }
  }
}'
)

echo "Patching Notebook $NOTEBOOK ..."

oc patch notebook "$NOTEBOOK" \
  -n "$NAMESPACE" \
  --type merge \
  -p "$PATCH"

echo "Patch complete."

STATEFULSET="$NOTEBOOK"

echo "Scaling $STATEFULSET to 0..."
oc scale statefulset "$STATEFULSET" -n "$NAMESPACE" --replicas=0

echo "Waiting for pod termination..."
oc wait --for=delete pod/"$NOTEBOOK-0" -n "$NAMESPACE" --timeout=120s || true

sleep 5

echo "Scaling $STATEFULSET to 1..."
oc scale statefulset "$STATEFULSET" -n "$NAMESPACE" --replicas=1

echo "Waiting for rollout..."
oc rollout status statefulset "$STATEFULSET" -n "$NAMESPACE" --timeout=300s

echo "Done."