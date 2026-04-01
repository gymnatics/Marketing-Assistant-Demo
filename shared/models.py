"""
Shared models and types for Marketing Assistant v2.

Contains Pydantic models, campaign themes, and common data structures
used across all microservices.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime


class CampaignTheme(str, Enum):
    LUXURY_GOLD = "luxury_gold"
    FESTIVE_RED = "festive_red"
    MODERN_BLACK = "modern_black"
    CLASSIC_CASINO = "classic_casino"


CAMPAIGN_THEMES = {
    "luxury_gold": {
        "name": "Luxury Gold",
        "description": "Elegant gold and champagne tones for premium experiences",
        "primary_color": "#D4AF37",
        "secondary_color": "#1a1a2e",
        "accent_color": "#FFD700",
        "background": "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
        "text_color": "#ffffff",
        "button_color": "#D4AF37",
        "button_text": "#1a1a2e"
    },
    "festive_red": {
        "name": "Festive Red",
        "description": "Elegant red and gold for celebrations and Chinese holidays",
        "primary_color": "#C41E3A",
        "secondary_color": "#8B0000",
        "accent_color": "#B8860B",
        "background": "linear-gradient(135deg, #8B0000 0%, #C41E3A 50%, #DC143C 100%)",
        "text_color": "#ffffff",
        "button_color": "#C41E3A",
        "button_text": "#ffffff"
    },
    "modern_black": {
        "name": "Modern Black",
        "description": "Sleek black and silver for sophisticated appeal",
        "primary_color": "#C0C0C0",
        "secondary_color": "#1a1a1a",
        "accent_color": "#E5E5E5",
        "background": "linear-gradient(135deg, #0d0d0d 0%, #1a1a1a 50%, #2d2d2d 100%)",
        "text_color": "#ffffff",
        "button_color": "#C0C0C0",
        "button_text": "#1a1a1a"
    },
    "classic_casino": {
        "name": "Classic Casino",
        "description": "Traditional green felt with gold accents",
        "primary_color": "#228B22",
        "secondary_color": "#006400",
        "accent_color": "#FFD700",
        "background": "linear-gradient(135deg, #004d00 0%, #006400 50%, #228B22 100%)",
        "text_color": "#ffffff",
        "button_color": "#FFD700",
        "button_text": "#004d00"
    }
}


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    PREVIEW_READY = "preview_ready"
    EMAIL_READY = "email_ready"
    APPROVED = "approved"
    LIVE = "live"
    FAILED = "failed"


class CustomerProfile(BaseModel):
    customer_id: str
    name: str
    name_en: Optional[str] = None
    email: str
    tier: str
    preferred_language: str = "en"
    interests: List[str] = Field(default_factory=list)
    total_spend: Optional[int] = None
    last_visit: Optional[str] = None
    source: Optional[str] = None


class CampaignRequest(BaseModel):
    campaign_name: str
    campaign_description: str
    hotel_name: str = "Simon Casino Resort"
    target_audience: str
    theme: CampaignTheme = CampaignTheme.LUXURY_GOLD
    start_date: str
    end_date: str


class CampaignData(BaseModel):
    id: str
    campaign_name: str
    campaign_description: str
    hotel_name: str
    target_audience: str
    theme: str
    start_date: str
    end_date: str
    status: CampaignStatus = CampaignStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    landing_page_html: Optional[str] = None
    preview_url: Optional[str] = None
    production_url: Optional[str] = None
    
    email_subject_en: Optional[str] = None
    email_body_en: Optional[str] = None
    email_subject_zh: Optional[str] = None
    email_body_zh: Optional[str] = None
    
    customer_list: List[CustomerProfile] = Field(default_factory=list)
    customer_count: int = 0
    
    error_message: Optional[str] = None


class AgentEvent(BaseModel):
    """Event published to Event Hub for real-time UI updates."""
    campaign_id: str
    event_type: str
    agent: Optional[str] = None
    task: Optional[str] = None
    status: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class A2ASkillInput(BaseModel):
    """Base model for A2A skill invocation."""
    pass


class GenerateLandingPageInput(A2ASkillInput):
    campaign_name: str
    campaign_description: str
    hotel_name: str
    theme: str
    start_date: str
    end_date: str


class GenerateLandingPageOutput(BaseModel):
    html: str
    status: str = "success"
    error: Optional[str] = None


class GetTargetCustomersInput(A2ASkillInput):
    target_audience: str
    limit: int = 50


class GetTargetCustomersOutput(BaseModel):
    customers: List[CustomerProfile]
    count: int
    recipient_type: str
    status: str = "success"
    error: Optional[str] = None


class GenerateEmailInput(A2ASkillInput):
    campaign_name: str
    campaign_description: str
    hotel_name: str
    campaign_url: str
    target_audience: str
    start_date: str
    end_date: str


class GenerateEmailOutput(BaseModel):
    email_subject_en: str
    email_body_en: str
    email_subject_zh: str
    email_body_zh: str
    status: str = "success"
    error: Optional[str] = None


class DeployPreviewInput(A2ASkillInput):
    campaign_id: str
    html_content: str
    namespace: str = "marketing-assistant-dev"


class DeployPreviewOutput(BaseModel):
    preview_url: str
    status: str = "success"
    error: Optional[str] = None


class DeployProductionInput(A2ASkillInput):
    campaign_id: str
    html_content: str
    namespace: str = "marketing-assistant-prod"


class DeployProductionOutput(BaseModel):
    production_url: str
    status: str = "success"
    error: Optional[str] = None


class SendEmailsInput(A2ASkillInput):
    campaign_id: str
    customers: List[CustomerProfile]
    email_subject_en: str
    email_body_en: str
    email_subject_zh: str
    email_body_zh: str


class SendEmailsOutput(BaseModel):
    sent_count: int
    status: str = "success"
    error: Optional[str] = None
