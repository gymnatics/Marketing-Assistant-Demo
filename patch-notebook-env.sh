#!/usr/bin/env bash
set -euo pipefail

# Usage:
# ./patch-notebook-env.sh <namespace> <notebook-name> <configmap-name> [container-name]
#
# Example:
# ./patch-notebook-env.sh marketing-assistant-v2 eval my-config eval

NAMESPACE="${1:?namespace required}"
NOTEBOOK="${2:?notebook name required}"
CONFIGMAP="${3:?configmap name required}"
CONTAINER="${4:-$NOTEBOOK}"

command -v oc >/dev/null || { echo "oc required"; exit 1; }
command -v jq >/dev/null || { echo "jq required"; exit 1; }

echo "Reading ConfigMap $CONFIGMAP in namespace $NAMESPACE..."

CM_JSON=$(oc get configmap "$CONFIGMAP" -n "$NAMESPACE" -o json)

KEYS=$(echo "$CM_JSON" | jq -r '.data | keys[]?')

if [[ -z "${KEYS:-}" ]]; then
  echo "No keys found in ConfigMap.data"
  exit 1
fi

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

echo "Reading existing env vars..."

EXISTING_ENV=$(
oc get notebook "$NOTEBOOK" -n "$NAMESPACE" -o json \
| jq --argjson idx "$INDEX" '
.spec.template.spec.containers[$idx].env // []
'
)

NEW_ENV="$EXISTING_ENV"

for KEY in $KEYS; do
  EXISTS=$(echo "$NEW_ENV" | jq --arg k "$KEY" 'map(select(.name==$k)) | length')

  if [[ "$EXISTS" -eq 0 ]]; then
    ITEM=$(jq -n \
      --arg key "$KEY" \
      --arg cm "$CONFIGMAP" '
      {
        name: $key,
        valueFrom: {
          configMapKeyRef: {
            name: $cm,
            key: $key
          }
        }
      }')

    NEW_ENV=$(echo "$NEW_ENV" | jq --argjson item "$ITEM" '. + [$item]')
  else
    echo "Skipping existing env var: $KEY"
  fi
done

PATCH=$(
jq -n \
  --arg cname "$CONTAINER" \
  --argjson env "$NEW_ENV" '
{
  spec: {
    template: {
      spec: {
        containers: [
          {
            name: $cname,
            env: $env
          }
        ]
      }
    }
  }
}
'
)

echo "Patching Notebook $NOTEBOOK ..."

oc patch notebook "$NOTEBOOK" \
  -n "$NAMESPACE" \
  --type merge \
  -p "$PATCH"

echo "Patch complete."

echo "Restarting Notebook StatefulSet..."

STATEFULSET="$NOTEBOOK"

echo "Scaling $STATEFULSET to 0..."
oc scale statefulset "$STATEFULSET" -n "$NAMESPACE" --replicas=0

echo "Waiting for pods to terminate..."
oc wait --for=delete pod/"$NOTEBOOK-0" -n "$NAMESPACE" --timeout=120s || true

sleep 5

echo "Scaling $STATEFULSET to 1..."
oc scale statefulset "$STATEFULSET" -n "$NAMESPACE" --replicas=1

echo "Waiting for pod to become Ready..."
oc rollout status statefulset "$STATEFULSET" -n "$NAMESPACE" --timeout=300s

echo "Done."