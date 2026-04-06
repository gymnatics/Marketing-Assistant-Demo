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
        return {"preferred_username": None, "scope": None, "error": "missing_authorization"}
    if isinstance(auth, (list, tuple)):
        auth = auth[0] if auth else None
    if not auth or not isinstance(auth, str):
        return {"preferred_username": None, "scope": None, "error": "invalid_authorization_header"}
    m = re.match(r"^\s*Bearer\s+(\S+)\s*$", auth, re.IGNORECASE)
    if not m:
        return {"preferred_username": None, "scope": None, "error": "not_bearer_token"}
    token = m.group(1)
    try:
        claims = decode_jwt_payload_unverified(token)
    except Exception as e:
        logger.debug("JWT payload decode failed: %s", e)
        return {"preferred_username": None, "scope": None, "error": "jwt_decode_failed"}
    return {
        "preferred_username": claims.get("preferred_username"),
        "scope": _normalize_scope_claim(claims.get("scope")),
    }


def get_bearer_auth_context() -> dict[str, Any]:
    """
    Authorization helper for MCP tools: decode the incoming Bearer JWT from the HTTP request.

    Must be called from tool code running in a request that supplies ``Authorization``
    (same pattern as ``get_http_headers(include={"authorization"})``).
    """
    headers = get_http_headers(include={"authorization"})
    return parse_authorization_bearer_jwt(headers)

def filter_customers_by_user_perm(customers: list) -> list:
    headers = get_http_headers(include={"authorization"})
    
    auth_ctx = parse_authorization_bearer_jwt(headers)
    
    if auth_ctx.get('preferred_username'):

        preferred_username = auth_ctx.get("preferred_username")
        scope = auth_ctx.get("scope")
        logger.info(f"JWT claims: preferred_username={preferred_username} scope={scope}")

        user_allowed_for_plat_tier = os.getenv("ALLOWED_PLATINUM_TIER", None)

        if user_allowed_for_plat_tier == preferred_username:
            return customers
        else: # not allowed, filter out
            logger.info (f"{preferred_username} has no permisison to list platinum members")
            return [c for c in customers if c.get('tier') != "platinum"]
    else:
        logger.info("No JWT token recieved")
        return customers
    

# Initialize FastMCP server
mcp = FastMCP("Customer Database MCP")

# Mock data for when MongoDB is unavailable
MOCK_CUSTOMERS = [
    {
        "customer_id": "VIP-001",
        "name": "张伟",
        "name_en": "Wei Zhang",
        "email": "wei.zhang@example.com",
        "tier": "platinum",
        "preferred_language": "zh-CN",
        "interests": ["baccarat", "fine dining", "spa"],
        "total_spend": 500000,
        "last_visit": "2026-03-15"
    },
    {
        "customer_id": "VIP-002",
        "name": "李明",
        "name_en": "Ming Li",
        "email": "ming.li@example.com",
        "tier": "platinum",
        "preferred_language": "zh-CN",
        "interests": ["blackjack", "golf", "wine"],
        "total_spend": 750000,
        "last_visit": "2026-03-20"
    },
    {
        "customer_id": "VIP-003",
        "name": "王芳",
        "name_en": "Fang Wang",
        "email": "fang.wang@example.com",
        "tier": "gold",
        "preferred_language": "zh-CN",
        "interests": ["slots", "shopping", "spa"],
        "total_spend": 250000,
        "last_visit": "2026-03-10"
    },
    {
        "customer_id": "VIP-004",
        "name": "John Smith",
        "name_en": "John Smith",
        "email": "john.smith@example.com",
        "tier": "platinum",
        "preferred_language": "en",
        "interests": ["poker", "golf", "fine dining"],
        "total_spend": 600000,
        "last_visit": "2026-03-18"
    },
    {
        "customer_id": "VIP-005",
        "name": "陈静",
        "name_en": "Jing Chen",
        "email": "jing.chen@example.com",
        "tier": "gold",
        "preferred_language": "zh-CN",
        "interests": ["baccarat", "spa", "shopping"],
        "total_spend": 300000,
        "last_visit": "2026-03-22"
    },
    {
        "customer_id": "VIP-006",
        "name": "Michael Wong",
        "name_en": "Michael Wong",
        "email": "michael.wong@example.com",
        "tier": "platinum",
        "preferred_language": "en",
        "interests": ["blackjack", "fine dining", "concerts"],
        "total_spend": 450000,
        "last_visit": "2026-03-19"
    },
    {
        "customer_id": "VIP-007",
        "name": "刘洋",
        "name_en": "Yang Liu",
        "email": "yang.liu@example.com",
        "tier": "diamond",
        "preferred_language": "zh-CN",
        "interests": ["baccarat", "private gaming", "yacht"],
        "total_spend": 2000000,
        "last_visit": "2026-03-25"
    },
    {
        "customer_id": "VIP-008",
        "name": "Sarah Johnson",
        "name_en": "Sarah Johnson",
        "email": "sarah.johnson@example.com",
        "tier": "gold",
        "preferred_language": "en",
        "interests": ["slots", "spa", "shows"],
        "total_spend": 180000,
        "last_visit": "2026-03-12"
    }
]

MOCK_PROSPECTS = [
    {
        "customer_id": "PROSPECT-001",
        "name": "赵雪",
        "name_en": "Xue Zhao",
        "email": "xue.zhao@example.com",
        "tier": "prospect",
        "preferred_language": "zh-CN",
        "interests": ["luxury travel", "fine dining"],
        "source": "hotel_inquiry"
    },
    {
        "customer_id": "PROSPECT-002",
        "name": "David Lee",
        "name_en": "David Lee",
        "email": "david.lee@example.com",
        "tier": "prospect",
        "preferred_language": "en",
        "interests": ["gaming", "entertainment"],
        "source": "website_signup"
    },
    {
        "customer_id": "PROSPECT-003",
        "name": "林美玲",
        "name_en": "Meiling Lin",
        "email": "meiling.lin@example.com",
        "tier": "prospect",
        "preferred_language": "zh-CN",
        "interests": ["spa", "shopping"],
        "source": "partner_referral"
    },
    {
        "customer_id": "PROSPECT-004",
        "name": "James Chen",
        "name_en": "James Chen",
        "email": "james.chen@example.com",
        "tier": "prospect",
        "preferred_language": "en",
        "interests": ["poker", "golf"],
        "source": "event_registration"
    },
    {
        "customer_id": "PROSPECT-005",
        "name": "周婷",
        "name_en": "Ting Zhou",
        "email": "ting.zhou@example.com",
        "tier": "prospect",
        "preferred_language": "zh-CN",
        "interests": ["luxury brands", "fine dining"],
        "source": "social_media"
    },
]


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
