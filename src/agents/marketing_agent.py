"""
Marketing Agent - Generates marketing email copy in English and Chinese.

Uses Qwen3-32B-FP8-dynamic model for natural language generation.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import Dict, Any, List
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import CampaignState
from config import settings


MARKETING_SYSTEM_PROMPT = """You are a luxury marketing copywriter for high-end Macau casinos.

Your task is to write compelling, personalized marketing email content that:
- Appeals to high-net-worth individuals
- Maintains brand elegance and exclusivity
- Uses sophisticated, refined language
- Includes clear calls-to-action
- Creates a sense of urgency and exclusivity

## Output Format:
You MUST provide content in BOTH English and Chinese (Simplified).

Structure your response EXACTLY as follows:

---ENGLISH_SUBJECT---
[English email subject line here]

---ENGLISH_BODY---
[English email body as HTML fragment - see formatting rules below]

---CHINESE_SUBJECT---
[Chinese email subject line here]

---CHINESE_BODY---
[Chinese email body as HTML fragment - see formatting rules below]

## Email Body HTML Formatting Rules:
- Use ONLY inline HTML tags like <h1>, <h2>, <p>, <strong>, <em>, <a>, <br>
- Do NOT include <!DOCTYPE>, <html>, <head>, <body>, or <style> tags
- Do NOT wrap content in any document structure
- For the CTA button, use: <a href="URL" style="background-color:#C41E3A;color:#ffffff;padding:12px 24px;text-decoration:none;border-radius:5px;display:inline-block;font-weight:bold;">Button Text</a>

## Email Style Guidelines:
- Keep subject lines under 60 characters
- Use elegant, premium language
- Include personalization placeholder {{customer_name}} for the greeting
- Add a prominent call-to-action button that links to the ACTUAL campaign URL provided (NOT a placeholder)
- Sign off with the hotel/casino name

IMPORTANT: The call-to-action button href MUST use the exact campaign URL provided in the prompt. Do NOT use placeholder text like "{{campaign_url}}" - use the actual URL.
"""


def parse_email_response(response: str) -> Dict[str, str]:
    """Parse the structured email response into components."""
    result = {
        "subject_en": "",
        "body_en": "",
        "subject_zh": "",
        "body_zh": ""
    }
    
    # Parse English subject
    if "---ENGLISH_SUBJECT---" in response:
        start = response.find("---ENGLISH_SUBJECT---") + len("---ENGLISH_SUBJECT---")
        end = response.find("---ENGLISH_BODY---") if "---ENGLISH_BODY---" in response else len(response)
        result["subject_en"] = response[start:end].strip()
    
    # Parse English body
    if "---ENGLISH_BODY---" in response:
        start = response.find("---ENGLISH_BODY---") + len("---ENGLISH_BODY---")
        end = response.find("---CHINESE_SUBJECT---") if "---CHINESE_SUBJECT---" in response else len(response)
        result["body_en"] = response[start:end].strip()
    
    # Parse Chinese subject
    if "---CHINESE_SUBJECT---" in response:
        start = response.find("---CHINESE_SUBJECT---") + len("---CHINESE_SUBJECT---")
        end = response.find("---CHINESE_BODY---") if "---CHINESE_BODY---" in response else len(response)
        result["subject_zh"] = response[start:end].strip()
    
    # Parse Chinese body
    if "---CHINESE_BODY---" in response:
        start = response.find("---CHINESE_BODY---") + len("---CHINESE_BODY---")
        result["body_zh"] = response[start:].strip()
    
    return result


def generate_email_content(
    campaign_name: str,
    campaign_description: str,
    hotel_name: str,
    campaign_url: str,
    target_audience: str,
    start_date: str = "",
    end_date: str = ""
) -> Dict[str, str]:
    """Generate email content using the language model with streaming."""
    import httpx
    import json
    
    date_info = ""
    if start_date and end_date:
        date_info = f"\n- **Campaign Period:** {start_date} to {end_date}"
    elif end_date:
        date_info = f"\n- **Offer Expires:** {end_date}"
    
    user_prompt = f"""Create a marketing email for the following campaign:

## Campaign Details:
- **Campaign Name:** {campaign_name}
- **Description:** {campaign_description}
- **Hotel/Casino:** {hotel_name}
- **Campaign Landing Page URL:** {campaign_url}
- **Target Audience:** {target_audience}{date_info}

## Requirements:
1. Create an enticing subject line that drives opens
2. Write an elegant email body with:
   - Personalized greeting using {{{{customer_name}}}} placeholder
   - Compelling description of the offer
   - Include the campaign dates ({start_date} to {end_date}) in the email body
   - Sense of exclusivity and urgency
   - A styled call-to-action button with href="{campaign_url}" (use this EXACT URL)
   - Professional sign-off from {hotel_name}
3. Use HTML formatting for the body (headers, paragraphs, button styling)
4. Provide both English and Chinese versions

CRITICAL: 
- The CTA button MUST link to: {campaign_url}
- Use the ACTUAL dates provided ({start_date} to {end_date}), NOT placeholders like [date]

Generate the email content now:"""

    url = f'{settings.LANG_MODEL_ENDPOINT}/chat/completions'
    headers = {
        'Authorization': f'Bearer {settings.LANG_MODEL_TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {
        'model': settings.LANG_MODEL_NAME,
        'messages': [
            {'role': 'system', 'content': MARKETING_SYSTEM_PROMPT},
            {'role': 'user', 'content': user_prompt}
        ],
        'max_tokens': 4000,
        'temperature': 0.7,
        'stream': True
    }
    
    response_content = ""
    with httpx.Client(timeout=300.0) as client:
        with client.stream('POST', url, json=data, headers=headers) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith('data: '):
                    json_str = line[6:]
                    if json_str.strip() == '[DONE]':
                        break
                    try:
                        chunk = json.loads(json_str)
                        if 'choices' in chunk and len(chunk['choices']) > 0:
                            delta = chunk['choices'][0].get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                response_content += content
                    except json.JSONDecodeError:
                        continue
    
    return parse_email_response(response_content)


def format_email_preview(subject: str, body: str, language: str) -> str:
    """Format email for preview display."""
    return f"""
<div style="border: 1px solid #ccc; border-radius: 8px; padding: 20px; margin: 10px 0; background: #f9f9f9;">
    <div style="border-bottom: 1px solid #ddd; padding-bottom: 10px; margin-bottom: 15px;">
        <strong>Subject ({language}):</strong> {subject}
    </div>
    <div style="background: white; padding: 15px; border-radius: 4px;">
        {body}
    </div>
</div>
"""


def marketing_agent(state: CampaignState) -> CampaignState:
    """
    Marketing Agent node for LangGraph workflow.
    
    Generates email content in English and Chinese based on:
    - Campaign details from state
    - Production URL for the campaign
    
    Updates state with:
    - email_subject_en, email_body_en
    - email_subject_zh, email_body_zh
    - current_step
    """
    print(f"[Marketing Agent] Generating email content for: {state['campaign_name']}")
    
    # Use production URL if available, otherwise preview URL
    campaign_url = state.get("production_url") or state.get("preview_url") or "{{campaign_url}}"
    
    try:
        # Generate email content
        email_content = generate_email_content(
            campaign_name=state["campaign_name"],
            campaign_description=state["campaign_description"],
            hotel_name=state["hotel_name"],
            campaign_url=campaign_url,
            target_audience=state["target_audience"],
            start_date=state.get("start_date", ""),
            end_date=state.get("end_date", "")
        )
        
        # Update state
        state["email_subject_en"] = email_content["subject_en"]
        state["email_body_en"] = email_content["body_en"]
        state["email_subject_zh"] = email_content["subject_zh"]
        state["email_body_zh"] = email_content["body_zh"]
        state["current_step"] = "email_generated"
        state["error_message"] = ""
        
        # Add to messages
        state["messages"] = state.get("messages", []) + [{
            "role": "assistant",
            "agent": "marketing",
            "content": f"Generated email content in English and Chinese for '{state['campaign_name']}'."
        }]
        
        print(f"[Marketing Agent] Successfully generated email content")
        
    except Exception as e:
        state["error_message"] = f"Marketing Agent error: {str(e)}"
        state["current_step"] = "error"
        print(f"[Marketing Agent] Error: {e}")
    
    return state


def simulate_email_send(state: CampaignState) -> CampaignState:
    """
    Simulate sending emails to customers.
    
    In simulation mode, just logs what would be sent.
    """
    print(f"[Marketing Agent] Simulating email send...")
    
    customer_list = state.get("customer_list", [])
    
    if not customer_list:
        # Use mock customers if none provided
        customer_list = [
            {"name": "张伟", "name_en": "Wei Zhang", "email": "wei.zhang@example.com", "preferred_language": "zh-CN"},
            {"name": "李明", "name_en": "Ming Li", "email": "ming.li@example.com", "preferred_language": "zh-CN"},
            {"name": "John Smith", "name_en": "John Smith", "email": "john.smith@example.com", "preferred_language": "en"},
        ]
    
    sent_count = 0
    for customer in customer_list:
        lang = customer.get("preferred_language", "en")
        name = customer.get("name") if lang == "zh-CN" else customer.get("name_en", customer.get("name"))
        email = customer.get("email")
        
        if lang == "zh-CN":
            subject = state.get("email_subject_zh", "")
            body = state.get("email_body_zh", "")
        else:
            subject = state.get("email_subject_en", "")
            body = state.get("email_body_en", "")
        
        # Simulate send
        print(f"  [SIMULATED] Sending to {name} <{email}> - Subject: {subject[:50]}...")
        sent_count += 1
    
    state["messages"] = state.get("messages", []) + [{
        "role": "assistant",
        "agent": "marketing",
        "content": f"[SIMULATED] Sent {sent_count} emails to customers."
    }]
    
    state["current_step"] = "emails_sent"
    
    return state


# For testing
if __name__ == "__main__":
    from src.state import create_initial_state
    
    # Create test state
    test_state = create_initial_state(
        campaign_name="Chinese New Year VIP Bonus",
        campaign_description="Celebrate the Year of the Dragon with an exclusive 50% deposit bonus for our VIP members. Limited time offer!",
        hotel_name="Grand Luxe Hotel & Casino",
        target_audience="VIP platinum members"
    )
    test_state["production_url"] = "https://cny-promo.grandluxe.casino"
    
    # Run agent
    result = marketing_agent(test_state)
    
    # Print result
    print("\n" + "="*50)
    print("English Subject:", result.get("email_subject_en", "Not generated"))
    print("="*50)
    print("English Body Preview:")
    print(result.get("email_body_en", "Not generated")[:500])
    print("\n" + "="*50)
    print("Chinese Subject:", result.get("email_subject_zh", "Not generated"))
    print("="*50)
