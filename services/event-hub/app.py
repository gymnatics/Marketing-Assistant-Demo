"""
Event Hub - Server-Sent Events (SSE) service for real-time UI updates.

Receives events from agents and broadcasts them to connected clients.
"""
import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Set
from flask import Flask, Response, request, jsonify
from flask_cors import CORS
import queue
import threading


app = Flask(__name__)
CORS(app)

event_queues: Dict[str, Set[queue.Queue]] = {}
event_lock = threading.Lock()


def get_campaign_queues(campaign_id: str) -> Set[queue.Queue]:
    """Get or create queue set for a campaign."""
    with event_lock:
        if campaign_id not in event_queues:
            event_queues[campaign_id] = set()
        return event_queues[campaign_id]


def add_client_queue(campaign_id: str, q: queue.Queue):
    """Add a client queue for a campaign."""
    with event_lock:
        if campaign_id not in event_queues:
            event_queues[campaign_id] = set()
        event_queues[campaign_id].add(q)


def remove_client_queue(campaign_id: str, q: queue.Queue):
    """Remove a client queue for a campaign."""
    with event_lock:
        if campaign_id in event_queues:
            event_queues[campaign_id].discard(q)
            if not event_queues[campaign_id]:
                del event_queues[campaign_id]


def broadcast_event(campaign_id: str, event_data: dict):
    """Broadcast event to all clients subscribed to a campaign."""
    with event_lock:
        queues = event_queues.get(campaign_id, set()).copy()
    
    event_json = json.dumps(event_data)
    
    for q in queues:
        try:
            q.put_nowait(event_json)
        except queue.Full:
            pass


@app.route("/healthz", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "Event Hub"})

@app.route("/readyz")
def readiness_check():
    return health_check()



@app.route("/events/<campaign_id>/publish", methods=["POST"])
def publish_event(campaign_id: str):
    """Publish an event for a campaign."""
    try:
        data = request.get_json()
        
        event = {
            "campaign_id": campaign_id,
            "event_type": data.get("event_type", "unknown"),
            "agent": data.get("agent"),
            "task": data.get("task"),
            "status": data.get("status"),
            "data": data.get("data", {}),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        broadcast_event(campaign_id, event)
        
        print(f"[Event Hub] Published: {event['event_type']} for campaign {campaign_id}")
        
        return jsonify({"status": "published"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/events/<campaign_id>", methods=["GET"])
def subscribe_events(campaign_id: str):
    """Subscribe to SSE events for a campaign."""
    
    def event_stream():
        client_queue = queue.Queue(maxsize=100)
        add_client_queue(campaign_id, client_queue)
        
        try:
            yield f"data: {json.dumps({'event_type': 'connected', 'campaign_id': campaign_id})}\n\n"
            
            while True:
                try:
                    event_data = client_queue.get(timeout=30)
                    yield f"data: {event_data}\n\n"
                except queue.Empty:
                    yield f": keepalive\n\n"
                    
        except GeneratorExit:
            pass
        finally:
            remove_client_queue(campaign_id, client_queue)
    
    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.route("/events/<campaign_id>/history", methods=["GET"])
def get_event_history(campaign_id: str):
    """Get recent event history for a campaign (placeholder)."""
    return jsonify([])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
