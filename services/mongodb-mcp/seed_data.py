"""
Seed MongoDB with mock customer and prospect data.

Reads data from the vertical config (config/verticals/*.json) if available,
otherwise falls back to hardcoded hotel-casino defaults.

Run once to populate the database:
    python seed_data.py
"""
import os
import sys
import time
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.vertical_config import seed_data

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://mongodb:27017")

_seed = seed_data()
MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", _seed.get("database_name", "casino_crm"))
CUSTOMERS = _seed.get("customers", [])
PROSPECTS = _seed.get("prospects", [])


def seed():
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
