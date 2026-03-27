"""
Configuration settings for the Macau Casino Marketing Assistant.
"""
import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Cluster Information
    CLUSTER_DOMAIN: str = "apps.cluster-qf44v.qf44v.sandbox543.opentlc.com"
    NAMESPACE: str = "0-marketing-assistant-demo"
    DEV_NAMESPACE: str = "0-marketing-assistant-demo-dev"
    PROD_NAMESPACE: str = "0-marketing-assistant-demo-prod"
    
    # Code Model (Coder + K8s Agents) - Qwen2.5-Coder-32B-FP8
    # Using custom route with 5min timeout (default KServe route has 30s timeout)
    CODE_MODEL_ENDPOINT: str = "https://qwen25-coder-custom-0-marketing-assistant-demo.apps.cluster-qf44v.qf44v.sandbox543.opentlc.com/v1"
    CODE_MODEL_NAME: str = "qwen25-coder-32b-fp8"
    CODE_MODEL_TOKEN: Optional[str] = None
    
    # Language Model (Marketing + Customer Agents)
    # Using custom route with 5min timeout (default KServe route has 30s timeout)
    LANG_MODEL_ENDPOINT: str = "https://qwen3-32b-custom-0-marketing-assistant-demo.apps.cluster-qf44v.qf44v.sandbox543.opentlc.com/v1"
    LANG_MODEL_NAME: str = "qwen3-32b-fp8-dynamic"
    LANG_MODEL_TOKEN: Optional[str] = None
    
    # MongoDB (Customer Database)
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DATABASE: str = "casino_crm"
    
    # Email settings
    EMAIL_MODE: str = "simulate"  # "simulate" or "send"
    RESEND_API_KEY: Optional[str] = None
    
    # Localization
    SUPPORTED_LANGUAGES: str = "en,zh-CN"
    DEFAULT_LANGUAGE: str = "en"
    
    # Application settings
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()


def get_code_model_client():
    """Get configured LLM client for code generation."""
    from langchain_openai import ChatOpenAI
    
    return ChatOpenAI(
        base_url=settings.CODE_MODEL_ENDPOINT,
        model=settings.CODE_MODEL_NAME,
        api_key=settings.CODE_MODEL_TOKEN or "dummy",
        default_headers={"Authorization": f"Bearer {settings.CODE_MODEL_TOKEN}"} if settings.CODE_MODEL_TOKEN else {},
        temperature=0.7,
        max_tokens=4000,
        timeout=120,
        max_retries=2,
    )


def get_lang_model_client():
    """Get configured LLM client for natural language tasks."""
    from langchain_openai import ChatOpenAI
    
    return ChatOpenAI(
        base_url=settings.LANG_MODEL_ENDPOINT,
        model=settings.LANG_MODEL_NAME,
        api_key=settings.LANG_MODEL_TOKEN or "dummy",
        default_headers={"Authorization": f"Bearer {settings.LANG_MODEL_TOKEN}"} if settings.LANG_MODEL_TOKEN else {},
        temperature=0.7,
        max_tokens=4000,
        timeout=180,
        max_retries=2,
    )
