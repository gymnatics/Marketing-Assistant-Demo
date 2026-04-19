"""
Seed MongoDB with mock customer and prospect data.

Run once to populate the casino_crm database:
    python seed_data.py
"""
import os
import time

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://mongodb:27017")
MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "casino_crm")

CUSTOMERS = [
    {"customer_id": "VIP-001", "name": "张伟", "name_en": "Wei Zhang", "email": "wei.zhang@example.com", "tier": "platinum", "preferred_language": "zh-CN", "interests": ["baccarat", "fine dining", "spa"], "total_spend": 500000, "last_visit": "2026-03-15"},
    {"customer_id": "VIP-002", "name": "李明", "name_en": "Ming Li", "email": "ming.li@example.com", "tier": "platinum", "preferred_language": "zh-CN", "interests": ["blackjack", "golf", "wine"], "total_spend": 750000, "last_visit": "2026-03-20"},
    {"customer_id": "VIP-003", "name": "王芳", "name_en": "Fang Wang", "email": "fang.wang@example.com", "tier": "gold", "preferred_language": "zh-CN", "interests": ["slots", "shopping", "spa"], "total_spend": 250000, "last_visit": "2026-03-10"},
    {"customer_id": "VIP-004", "name": "John Smith", "name_en": "John Smith", "email": "john.smith@example.com", "tier": "platinum", "preferred_language": "en", "interests": ["poker", "golf", "fine dining"], "total_spend": 600000, "last_visit": "2026-03-18"},
    {"customer_id": "VIP-005", "name": "陈静", "name_en": "Jing Chen", "email": "jing.chen@example.com", "tier": "gold", "preferred_language": "zh-CN", "interests": ["baccarat", "spa", "shopping"], "total_spend": 300000, "last_visit": "2026-03-22"},
    {"customer_id": "VIP-006", "name": "Michael Wong", "name_en": "Michael Wong", "email": "michael.wong@example.com", "tier": "platinum", "preferred_language": "en", "interests": ["blackjack", "fine dining", "concerts"], "total_spend": 450000, "last_visit": "2026-03-19"},
    {"customer_id": "VIP-007", "name": "刘洋", "name_en": "Yang Liu", "email": "yang.liu@example.com", "tier": "diamond", "preferred_language": "zh-CN", "interests": ["baccarat", "private gaming", "yacht"], "total_spend": 2000000, "last_visit": "2026-03-25"},
    {"customer_id": "VIP-008", "name": "Sarah Johnson", "name_en": "Sarah Johnson", "email": "sarah.johnson@example.com", "tier": "gold", "preferred_language": "en", "interests": ["slots", "spa", "shows"], "total_spend": 180000, "last_visit": "2026-03-12"},
]

PROSPECTS = [
    {"customer_id": "PROSPECT-001", "name": "赵雪", "name_en": "Xue Zhao", "email": "xue.zhao@example.com", "tier": "prospect", "preferred_language": "zh-CN", "interests": ["luxury travel", "fine dining"], "source": "hotel_inquiry"},
    {"customer_id": "PROSPECT-002", "name": "David Lee", "name_en": "David Lee", "email": "david.lee@example.com", "tier": "prospect", "preferred_language": "en", "interests": ["gaming", "entertainment"], "source": "website_signup"},
    {"customer_id": "PROSPECT-003", "name": "林美玲", "name_en": "Meiling Lin", "email": "meiling.lin@example.com", "tier": "prospect", "preferred_language": "zh-CN", "interests": ["spa", "shopping"], "source": "partner_referral"},
    {"customer_id": "PROSPECT-004", "name": "James Chen", "name_en": "James Chen", "email": "james.chen@example.com", "tier": "prospect", "preferred_language": "en", "interests": ["poker", "golf"], "source": "event_registration"},
    {"customer_id": "PROSPECT-005", "name": "周婷", "name_en": "Ting Zhou", "email": "ting.zhou@example.com", "tier": "prospect", "preferred_language": "zh-CN", "interests": ["luxury brands", "fine dining"], "source": "social_media"},
]

def seed():
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure

    print(f"[Seed] Connecting to {MONGODB_URI}...")
    for attempt in range(10):
        try:
            client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            client.server_info()
            break
        except ConnectionFailure:
            print(f"[Seed] Waiting for MongoDB... (attempt {attempt + 1}/10)")
            time.sleep(3)
    else:
        print("[Seed] Could not connect to MongoDB after 10 attempts")
        return

    db = client[MONGODB_DATABASE]

    db.customers.drop()
    db.prospects.drop()

    if CUSTOMERS:
        db.customers.insert_many(CUSTOMERS)
        print(f"[Seed] Inserted {len(CUSTOMERS)} customers into {MONGODB_DATABASE}.customers")

    if PROSPECTS:
        db.prospects.insert_many(PROSPECTS)
        print(f"[Seed] Inserted {len(PROSPECTS)} prospects into {MONGODB_DATABASE}.prospects")

    db.customers.create_index("tier")
    db.customers.create_index("total_spend")
    db.customers.create_index("customer_id", unique=True)
    db.prospects.create_index("customer_id", unique=True)
    print("[Seed] Indexes created")

    print("[Seed] Done!")
    client.close()


if __name__ == "__main__":
    seed()
