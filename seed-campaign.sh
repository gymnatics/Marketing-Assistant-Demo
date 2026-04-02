#!/bin/bash
# Seed a pre-generated campaign through the API
# Run this after all services are up and ready

API_URL="${API_URL:-https://marketing-assistant-v2-marketing-assistant-v2.apps.cluster-qf44v.qf44v.sandbox543.opentlc.com}"

echo "=== Seeding pre-generated campaign ==="
echo "API: $API_URL"
echo ""

# Create campaign
echo "Creating campaign..."
RESULT=$(curl -sk -X POST "$API_URL/api/campaigns" \
  -H "Content-Type: application/json" \
  -d '{
    "campaign_name": "CNY VIP Gala",
    "campaign_description": "Ring in the Year of the Snake with an exclusive celebration for our most distinguished guests. Five-star dining, private gaming salons, and world-class entertainment. Limited to 100 invitations.",
    "hotel_name": "Simon Casino Resort",
    "target_audience": "Platinum members",
    "theme": "festive_red",
    "start_date": "2026-04-15",
    "end_date": "2026-05-15"
  }')

echo "Result: $RESULT"
CAMPAIGN_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('campaign_id',''))" 2>/dev/null)

if [ -z "$CAMPAIGN_ID" ]; then
    echo "Failed to create campaign"
    exit 1
fi

echo "Campaign ID: $CAMPAIGN_ID"
echo ""

# Trigger generation
echo "Triggering landing page generation..."
curl -sk -X POST "$API_URL/api/campaigns/$CAMPAIGN_ID/generate" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2)[:200])" 2>/dev/null
echo ""

# Wait for generation
echo "Waiting for generation to complete..."
for i in $(seq 1 60); do
    sleep 5
    STATUS=$(curl -sk "$API_URL/api/campaigns/$CAMPAIGN_ID" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null)
    echo "  Status: $STATUS ($((i*5))s)"
    if [ "$STATUS" = "preview_ready" ] || [ "$STATUS" = "failed" ]; then
        break
    fi
done

if [ "$STATUS" != "preview_ready" ]; then
    echo "Generation did not complete (status: $STATUS)"
    exit 1
fi

echo ""
echo "=== Pre-generated campaign ready ==="
echo "Campaign ID: $CAMPAIGN_ID"
PREVIEW=$(curl -sk "$API_URL/api/campaigns/$CAMPAIGN_ID" | python3 -c "import sys,json; print(json.load(sys.stdin).get('preview_url',''))" 2>/dev/null)
echo "Preview URL: $PREVIEW"
echo ""
echo "The campaign will appear on the dashboard as an active campaign."
echo "You can continue from the UI: generate emails, go live, etc."
