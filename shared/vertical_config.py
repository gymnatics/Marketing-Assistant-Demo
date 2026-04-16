"""
Vertical configuration loader.

Loads the active vertical config from:
1. VERTICAL_CONFIG_PATH env var (path to JSON file)
2. VERTICAL_CONFIG env var (vertical ID like "hotel-casino")
3. Default: hotel-casino

All services import `get_config()` to access vertical-specific strings.
"""
import json
import os
from typing import Any
from functools import lru_cache

CONFIG_DIR = os.path.join(os.path.dirname(__file__), '..', 'config', 'verticals')

@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    config_path = os.environ.get("VERTICAL_CONFIG_PATH", "")
    if config_path and os.path.isfile(config_path):
        with open(config_path) as f:
            return json.load(f)

    vertical_id = os.environ.get("VERTICAL_CONFIG", "hotel-casino")
    candidate = os.path.join(CONFIG_DIR, f"{vertical_id}.json")
    if os.path.isfile(candidate):
        with open(candidate) as f:
            return json.load(f)

    # Fallback: try mounted ConfigMap (deploy.sh injects as a file)
    mounted = "/etc/vertical-config/vertical.json"
    if os.path.isfile(mounted):
        with open(mounted) as f:
            return json.load(f)

    print(f"[vertical_config] WARNING: No config found for '{vertical_id}', using empty defaults")
    return {}


def brand(key: str, default: str = "") -> str:
    return get_config().get("brand", {}).get(key, default)

def properties() -> list[str]:
    return get_config().get("properties", [])

def tiers() -> dict:
    return get_config().get("tiers", {})

def top_tier_role() -> str:
    return get_config().get("tiers", {}).get("top", {}).get("role", "platinum-access")

def top_tier_id() -> str:
    return get_config().get("tiers", {}).get("top", {}).get("id", "platinum")

def audience_suggestions() -> list[str]:
    return get_config().get("audience_suggestions", [])

def themes() -> dict:
    return get_config().get("themes", {})

def competitors() -> list[str]:
    return get_config().get("competitors", [])

def prompt(key: str, default: str = "") -> str:
    return get_config().get("prompts", {}).get(key, default)

def quick_start_presets() -> list[dict]:
    return get_config().get("quick_start_presets", [])

def seed_data() -> dict:
    return get_config().get("seed_data", {})

def property_label() -> str:
    return get_config().get("property_label", "Property")

def guardrail_presets() -> list[dict]:
    return get_config().get("guardrail_presets", [])
