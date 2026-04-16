"""
MongoDB MCP Server - FastMCP wrapper for customer database access.

Provides tools for retrieving VIP customer profiles for marketing campaigns.
Supports role-based filtering via 'allowed_tiers' parameter for KAgenti integration.
"""
import base64
import json
import logging
import os
import re
import sys
from typing import Any, List, Mapping, Optional

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

logger = logging.getLogger("mongodb_mcp")

TIER_SCOPES = {
    "tier-admin": ["diamond", "platinum", "gold"],
    "tier-diamond": ["diamond", "platinum", "gold"],
    "tier-platinum": ["platinum", "gold"],
    "tier-gold": ["gold"],
}

def filter_by_allowed_tiers(customers: list, allowed_tiers: str = "") -> list:
    """Filter customer list by allowed tiers. Empty = no filter (backward compatible)."""
    if not allowed_tiers:
        return customers
    tiers = TIER_SCOPES.get(allowed_tiers, allowed_tiers.split(","))
    return [c for c in customers if c.get("tier", "") in tiers]


def _log_http_headers(headers: Mapping[str, Any]) -> None:
    logger.debug("HTTP headers: %s", headers)

def _normalize_scope_claim(value: Any) -> Optional[str]:
    """Keycloak usually sends `scope` as a space-separated string; normalize other shapes."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None    
    return value

def decode_jwt_payload_unverified(token: str) -> dict[str, Any]:
    """
    Decode JWT payload without verifying the signature.
    Use only when the token is already validated by an API gateway or IdP proxy.
    """
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ValueError("JWT must have three segments")
    payload_b64 = parts[1]
    pad = "=" * ((4 - len(payload_b64) % 4) % 4)
    raw = base64.urlsafe_b64decode(payload_b64 + pad)
    return json.loads(raw.decode("utf-8"))


def parse_authorization_bearer_jwt(headers: Mapping[str, Any]) -> dict[str, Any]:
    """
    Read `Authorization: Bearer <jwt>` from headers and return Keycloak-oriented claims.

    Returns a dict with ``preferred_username``, ``scope``, and optionally ``error``
    if the header is missing, not Bearer, or the JWT payload cannot be decoded.
    Signature is not verified (see ``decode_jwt_payload_unverified``).
    """
    auth: Any = None
    for key in headers:
        if str(key).lower() == "authorization":
            auth = headers[key]
            break
    if auth is None:
        return {"preferred_username": None, "scope": None, "roles": [], "error": "missing_authorization"}
    if isinstance(auth, (list, tuple)):
        auth = auth[0] if auth else None
    if not auth or not isinstance(auth, str):
        return {"preferred_username": None, "scope": None, "roles": [], "error": "invalid_authorization_header"}
    m = re.match(r"^\s*Bearer\s+(\S+)\s*$", auth, re.IGNORECASE)
    if not m:
        return {"preferred_username": None, "scope": None, "roles": [], "error": "not_bearer_token"}
    token = m.group(1)
    try:
        claims = decode_jwt_payload_unverified(token)
    except Exception as e:
        logger.debug("JWT payload decode failed: %s", e)
        return {"preferred_username": None, "scope": None, "roles": [], "error": "jwt_decode_failed"}
    realm_access = claims.get("realm_access", {})
    roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
    return {
        "preferred_username": claims.get("preferred_username"),
        "scope": _normalize_scope_claim(claims.get("scope")),
        "roles": roles,
    }


def get_bearer_auth_context() -> dict[str, Any]:
    """
    Authorization helper for MCP tools: decode the incoming Bearer JWT from the HTTP request.

    Must be called from tool code running in a request that supplies ``Authorization``
    (same pattern as ``get_http_headers(include={"authorization"})``).
    """
    headers = get_http_headers(include={"authorization"})
    return parse_authorization_bearer_jwt(headers)

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
try:
    from shared.vertical_config import top_tier_role, top_tier_id
    PLATINUM_ROLE = top_tier_role()
    PLATINUM_TIER_ID = top_tier_id()
except ImportError:
    PLATINUM_ROLE = os.getenv("PLATINUM_ACCESS_ROLE", "platinum-access")
    PLATINUM_TIER_ID = "platinum"

def filter_customers_by_user_perm(customers: list) -> list:
    headers = get_http_headers(include={"authorization"})
    auth_ctx = parse_authorization_bearer_jwt(headers)

    if not auth_ctx.get("preferred_username"):
        logger.info("No JWT token received — returning unfiltered data")
        return customers

    username = auth_ctx["preferred_username"]
    roles = auth_ctx.get("roles", [])
    scope = auth_ctx.get("scope")
    logger.info(f"JWT claims: preferred_username={username} roles={roles} scope={scope}")

    # Primary: check Keycloak realm role (managed in Keycloak, no pod restart needed)
    if PLATINUM_ROLE in roles:
        logger.info(f"{username} has '{PLATINUM_ROLE}' role — full access")
        return customers

    # Fallback: legacy env var check (for clusters without Keycloak roles configured)
    legacy_allowed = os.getenv("ALLOWED_PLATINUM_TIER", "")
    if legacy_allowed and legacy_allowed == username:
        logger.info(f"{username} matches ALLOWED_PLATINUM_TIER env var — full access (legacy)")
        return customers

    logger.info(f"{username} lacks '{PLATINUM_ROLE}' role — filtering out {PLATINUM_TIER_ID} members")
    return [c for c in customers if c.get("tier") != PLATINUM_TIER_ID]
    

# Initialize FastMCP server
mcp = FastMCP("Customer Database MCP")

# Mock data for when MongoDB is unavailable
from seed_data import CUSTOMERS as MOCK_CUSTOMERS, PROSPECTS as MOCK_PROSPECTS

def get_mongodb_client() -> Optional[MongoClient]:
    """Get MongoDB client connection."""
    try:
        uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.server_info()
        return client
    except ConnectionFailure as e:
        logger.warning("MongoDB connection failed: %s", e)
        return None


@mcp.tool
def get_customers_by_tier(tier: str, limit: int = 50) -> List[dict]:
    """
    Retrieve VIP customers by membership tier.
    
    Args:
        tier: Membership tier (platinum, gold, diamond)
        limit: Maximum number of customers to return
    
    Returns:
        List of customer profiles matching the tier
    """
    client = get_mongodb_client()
    
    if client is None:
        logger.warning("Using mock data (MongoDB unavailable)")
        return filter_customers_by_user_perm([c for c in MOCK_CUSTOMERS if c["tier"] == tier])[:limit]
    
    try:
        db = client[os.environ.get("MONGODB_DATABASE", "casino_crm")]
        customers = list(db.customers.find({"tier": tier}).limit(limit))
        for c in customers:
            if "_id" in c:
                c["_id"] = str(c["_id"])
        return filter_customers_by_user_perm(customers)
    except Exception as e:
        logger.error("Query error in get_customers_by_tier: %s", e)
        return filter_customers_by_user_perm([c for c in MOCK_CUSTOMERS if c["tier"] == tier])[:limit]
    finally:
        client.close()


@mcp.tool
def get_prospects(limit: int = 50) -> List[dict]:
    """
    Retrieve prospect list for new member campaigns.
    
    Prospects are potential customers who have shown interest but are not yet members.
    
    Args:
        limit: Maximum number of prospects to return
    
    Returns:
        List of prospect profiles
    """

    client = get_mongodb_client()

    if client is None:
        logger.warning("Using mock data (MongoDB unavailable)")
        return MOCK_PROSPECTS[:limit]
    
    try:
        db = client[os.environ.get("MONGODB_DATABASE", "casino_crm")]
        prospects = list(db.prospects.find().limit(limit))
        for p in prospects:
            if "_id" in p:
                p["_id"] = str(p["_id"])
        return filter_customers_by_user_perm(prospects)
    except Exception as e:
        logger.error("Query error in get_prospects: %s", e)
        return filter_customers_by_user_perm(MOCK_PROSPECTS)[:limit]
    finally:
        client.close()


@mcp.tool
def get_all_vip_customers(limit: int = 100, allowed_tiers: str = "") -> List[dict]:
    """
    Retrieve all VIP customers regardless of tier.
    
    Args:
        limit: Maximum number of customers to return
        allowed_tiers: Optional role-based filter (e.g., 'tier-admin', 'tier-gold'). Empty = all tiers.
    
    Returns:
        List of all VIP customer profiles
    """
    client = get_mongodb_client()

    if client is None:
        logger.warning("Using mock data (MongoDB unavailable)")
        return filter_by_allowed_tiers(MOCK_CUSTOMERS, allowed_tiers)[:limit]
    
    try:
        db = client[os.environ.get("MONGODB_DATABASE", "casino_crm")]
        customers = list(db.customers.find().limit(limit))
        for c in customers:
            if "_id" in c:
                c["_id"] = str(c["_id"])
        return filter_customers_by_user_perm(filter_by_allowed_tiers(customers, allowed_tiers))
    except Exception as e:
        logger.error("Query error in get_all_vip_customers: %s", e)
        return filter_by_allowed_tiers(MOCK_CUSTOMERS, allowed_tiers)[:limit]
    finally:
        client.close()


@mcp.tool
def get_high_spend_customers(min_spend: int = 500000, limit: int = 50) -> List[dict]:
    """
    Retrieve customers with total spend above threshold.
    
    Args:
        min_spend: Minimum total spend amount
        limit: Maximum number of customers to return
    
    Returns:
        List of high-spending customer profiles
    """
    client = get_mongodb_client()
    
    if client is None:
        logger.warning("Using mock data (MongoDB unavailable)")
        return filter_customers_by_user_perm([c for c in MOCK_CUSTOMERS if c.get("total_spend", 0) >= min_spend])[:limit]
    
    try:
        db = client[os.environ.get("MONGODB_DATABASE", "casino_crm")]
        customers = list(db.customers.find({"total_spend": {"$gte": min_spend}}).limit(limit))
        for c in customers:
            if "_id" in c:
                c["_id"] = str(c["_id"])
        return filter_customers_by_user_perm(customers)
    except Exception as e:
        logger.error("Query error in get_high_spend_customers: %s", e)
        return filter_customers_by_user_perm([c for c in MOCK_CUSTOMERS if c.get("total_spend", 0) >= min_spend])[:limit]
    finally:
        client.close()


@mcp.tool
def search_customers(query: str, limit: int = 20) -> List[dict]:
    """
    Search customers by name or email.
    
    Args:
        query: Search string to match against name or email
        limit: Maximum number of customers to return
    
    Returns:
        List of matching customer profiles
    """
    client = get_mongodb_client()
    query_lower = query.lower()
    
    if client is None:
        logger.warning("Using mock data (MongoDB unavailable)")
        return filter_customers_by_user_perm([
            c for c in MOCK_CUSTOMERS 
            if query_lower in c.get("name", "").lower() 
            or query_lower in c.get("name_en", "").lower()
            or query_lower in c.get("email", "").lower()
        ])[:limit]
    
    try:
        db = client[os.environ.get("MONGODB_DATABASE", "casino_crm")]
        customers = list(db.customers.find({
            "$or": [
                {"name": {"$regex": query, "$options": "i"}},
                {"name_en": {"$regex": query, "$options": "i"}},
                {"email": {"$regex": query, "$options": "i"}}
            ]
        }).limit(limit))
        for c in customers:
            if "_id" in c:
                c["_id"] = str(c["_id"])
        return filter_customers_by_user_perm(customers)
    except Exception as e:
        logger.error("Query error in search_customers: %s", e)
        return filter_customers_by_user_perm([
            c for c in MOCK_CUSTOMERS 
            if query_lower in c.get("name", "").lower() 
            or query_lower in c.get("name_en", "").lower()
            or query_lower in c.get("email", "").lower()
        ])[:limit]
    finally:
        client.close()


@mcp.tool
def get_customer_count_by_tier() -> dict:
    """
    Get count of customers in each membership tier.
    
    Returns:
        Dictionary with tier names as keys and counts as values
    """
    client = get_mongodb_client()
    
    if client is None:
        logger.warning("Using mock data (MongoDB unavailable)")
        counts = {}
        for c in filter_customers_by_user_perm(MOCK_CUSTOMERS):
            tier = c.get("tier", "unknown")
            counts[tier] = counts.get(tier, 0) + 1
        return counts
    
    try:
        db = client[os.environ.get("MONGODB_DATABASE", "casino_crm")]
        pipeline = [
            {"$group": {"_id": "$tier", "count": {"$sum": 1}}}
        ]
        result = filter_customers_by_user_perm(list(db.customers.aggregate(pipeline)))
        return {r["_id"]: r["count"] for r in result}
    except Exception as e:
        logger.error("Query error in get_customer_count_by_tier: %s", e)
        counts = {}
        for c in filter_customers_by_user_perm(MOCK_CUSTOMERS):
            tier = c.get("tier", "unknown")
            counts[tier] = counts.get(tier, 0) + 1
        return counts
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="MongoDB MCP Server")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    logger.info(f"[MongoDB MCP] Starting streamable-http MCP server on 0.0.0.0:{args.port}")
    logger.info(f"[MongoDB MCP] MCP endpoint: http://0.0.0.0:{args.port}/mcp")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=args.port)
