"""
Customer Agent - Retrieves VIP customer profiles from MongoDB.

Uses Qwen3-32B-FP8-dynamic model for natural language queries.
Connects to MongoDB for customer data.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import Dict, Any, List, Optional
from src.state import CampaignState
from config import settings


# Mock prospect data for "New members" campaigns (people who are NOT yet members)
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

# Mock customer data for demo (used when MongoDB is not available)
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


def get_mongodb_client():
    """Get MongoDB client connection."""
    try:
        from pymongo import MongoClient
        client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
        # Test connection
        client.server_info()
        return client
    except Exception as e:
        print(f"[Customer Agent] MongoDB connection failed: {e}")
        return None


def query_customers_from_mongodb(
    tier: Optional[str] = None,
    min_spend: Optional[int] = None,
    interests: Optional[List[str]] = None,
    limit: int = 50
) -> List[Dict]:
    """Query customers from MongoDB."""
    client = get_mongodb_client()
    
    if client is None:
        print("[Customer Agent] Using mock customer data (MongoDB unavailable)")
        return filter_mock_customers(tier, min_spend, interests, limit)
    
    try:
        db = client[settings.MONGODB_DATABASE]
        collection = db["customers"]
        
        # Build query
        query = {}
        if tier:
            query["tier"] = tier
        if min_spend:
            query["total_spend"] = {"$gte": min_spend}
        if interests:
            query["interests"] = {"$in": interests}
        
        # Execute query
        customers = list(collection.find(query).limit(limit))
        
        # Convert ObjectId to string
        for customer in customers:
            if "_id" in customer:
                customer["_id"] = str(customer["_id"])
        
        return customers
        
    except Exception as e:
        print(f"[Customer Agent] MongoDB query error: {e}")
        return filter_mock_customers(tier, min_spend, interests, limit)
    finally:
        client.close()


def filter_mock_customers(
    tier: Optional[str] = None,
    min_spend: Optional[int] = None,
    interests: Optional[List[str]] = None,
    limit: int = 50
) -> List[Dict]:
    """Filter mock customers based on criteria."""
    filtered = MOCK_CUSTOMERS.copy()
    
    if tier:
        filtered = [c for c in filtered if c["tier"] == tier]
    
    if min_spend:
        filtered = [c for c in filtered if c["total_spend"] >= min_spend]
    
    if interests:
        filtered = [c for c in filtered if any(i in c["interests"] for i in interests)]
    
    return filtered[:limit]


def get_customers_by_tier(tier: str) -> List[Dict]:
    """Get customers by membership tier."""
    return query_customers_from_mongodb(tier=tier)


def get_customers_by_spend(min_spend: int) -> List[Dict]:
    """Get customers with minimum spend threshold."""
    return query_customers_from_mongodb(min_spend=min_spend)


def get_customers_by_interests(interests: List[str]) -> List[Dict]:
    """Get customers with matching interests."""
    return query_customers_from_mongodb(interests=interests)


def get_all_vip_customers(limit: int = 100) -> List[Dict]:
    """Get all VIP customers."""
    return query_customers_from_mongodb(limit=limit)


def get_prospects() -> List[Dict]:
    """Get prospect list for new member campaigns."""
    return MOCK_PROSPECTS.copy()


def customer_agent(state: CampaignState) -> CampaignState:
    """
    Customer Agent node for LangGraph workflow.
    
    Retrieves customer profiles based on target audience.
    For "new members" campaigns, returns prospects (non-members) instead.
    
    Updates state with:
    - customer_list
    - current_step
    """
    print(f"[Customer Agent] Retrieving customers for: {state['target_audience']}")
    
    target_audience = state.get("target_audience", "").lower()
    
    try:
        # Determine query based on target audience
        if "new" in target_audience:
            # New members = prospects who are NOT yet customers
            customers = get_prospects()
            recipient_type = "prospects"
        elif "platinum" in target_audience:
            customers = get_customers_by_tier("platinum")
            recipient_type = "customers"
        elif "diamond" in target_audience:
            customers = get_customers_by_tier("diamond")
            recipient_type = "customers"
        elif "gold" in target_audience:
            customers = get_customers_by_tier("gold")
            recipient_type = "customers"
        elif "high spend" in target_audience or "high-spend" in target_audience:
            customers = get_customers_by_spend(500000)
            recipient_type = "customers"
        else:
            # Default: get all VIP customers
            customers = get_all_vip_customers()
            recipient_type = "customers"
        
        # Update state
        state["customer_list"] = customers
        state["current_step"] = "customers_retrieved"
        state["error_message"] = ""
        
        # Add to messages
        state["messages"] = state.get("messages", []) + [{
            "role": "assistant",
            "agent": "customer",
            "content": f"Retrieved {len(customers)} {recipient_type} matching '{state['target_audience']}'."
        }]
        
        print(f"[Customer Agent] Retrieved {len(customers)} {recipient_type}")
        
    except Exception as e:
        state["error_message"] = f"Customer Agent error: {str(e)}"
        state["current_step"] = "error"
        print(f"[Customer Agent] Error: {e}")
    
    return state


def seed_mongodb_with_mock_data():
    """Seed MongoDB with mock customer data (for setup)."""
    client = get_mongodb_client()
    
    if client is None:
        print("[Customer Agent] Cannot seed - MongoDB unavailable")
        return False
    
    try:
        db = client[settings.MONGODB_DATABASE]
        collection = db["customers"]
        
        # Clear existing data
        collection.delete_many({})
        
        # Insert mock data
        collection.insert_many(MOCK_CUSTOMERS)
        
        print(f"[Customer Agent] Seeded {len(MOCK_CUSTOMERS)} customers to MongoDB")
        return True
        
    except Exception as e:
        print(f"[Customer Agent] Seed error: {e}")
        return False
    finally:
        client.close()


# For testing
if __name__ == "__main__":
    from src.state import create_initial_state
    
    # Create test state
    test_state = create_initial_state(
        campaign_name="Test Campaign",
        campaign_description="Test",
        target_audience="VIP platinum members"
    )
    
    # Run agent
    result = customer_agent(test_state)
    
    # Print result
    print("\n" + "="*50)
    print(f"Retrieved {len(result.get('customer_list', []))} customers:")
    print("="*50)
    for customer in result.get("customer_list", [])[:5]:
        print(f"  - {customer['name_en']} ({customer['tier']}) - ${customer['total_spend']:,}")
