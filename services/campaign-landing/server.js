const express = require("express");
const fs = require("fs");

const app = express();
const PORT = process.env.PORT || 8080;

const DATA_DIR = process.env.DATA_DIR || "/data";
const TEMPLATE_PATH = `${DATA_DIR}/template.html`;
const CAMPAIGN_PATH = `${DATA_DIR}/campaign.json`;
const MONGODB_MCP_URL = process.env.MONGODB_MCP_URL || "http://mongodb-mcp:8090";

let customerCache = {};
let cacheTime = 0;
const CACHE_TTL = 60000;

function loadFile(filePath) {
  try { return fs.readFileSync(filePath, "utf-8"); } catch { return null; }
}

function getCampaign() {
  const raw = loadFile(CAMPAIGN_PATH);
  try { return raw ? JSON.parse(raw) : {}; } catch { return {}; }
}

async function fetchCustomerFromMCP(customerId) {
  if (customerCache[customerId] && Date.now() - cacheTime < CACHE_TTL) {
    return customerCache[customerId];
  }

  try {
    const resp = await fetch(`${MONGODB_MCP_URL}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "initialize",
        params: { capabilities: {} },
        id: 1,
      }),
    });

    if (!resp.ok) throw new Error(`MCP init failed: ${resp.status}`);

    const searchResp = await fetch(`${MONGODB_MCP_URL}/mcp`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "mcp-session-id": resp.headers.get("mcp-session-id") || "",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "tools/call",
        params: {
          name: "get_all_vip_customers",
          arguments: { limit: 100 },
        },
        id: 2,
      }),
    });

    if (searchResp.ok) {
      const data = await searchResp.json();
      if (data.result && data.result.content) {
        const customers = JSON.parse(data.result.content[0].text);
        customerCache = {};
        for (const c of customers) {
          customerCache[c.customer_id] = c;
        }
        cacheTime = Date.now();
        return customerCache[customerId] || null;
      }
    }
  } catch (e) {
    console.log(`[Campaign Landing] MCP fetch failed, trying ConfigMap fallback: ${e.message}`);
  }

  // Fallback to ConfigMap file if MCP fails
  try {
    const raw = loadFile(`${DATA_DIR}/customers.json`);
    if (raw) {
      const list = JSON.parse(raw);
      for (const c of list) {
        customerCache[c.customer_id] = c;
      }
      cacheTime = Date.now();
      return customerCache[customerId] || null;
    }
  } catch {}

  return null;
}

function personalize(html, customer, campaign) {
  const name = customer.name_en || customer.name || "Valued Guest";
  const firstName = (customer.name_en || customer.name || "Guest").split(" ")[0];
  const tier = (customer.tier || "VIP").charAt(0).toUpperCase() + (customer.tier || "vip").slice(1);
  const interests = (customer.interests || []).join(", ");

  const greetingEn = `Your Exclusive Experience Awaits, ${firstName}`;
  const greetingZh = `${customer.name || firstName}，您的专属体验已就绪`;
  const greeting = `${greetingEn}<br><span style="font-size:0.6em;opacity:0.7">${greetingZh}</span>`;

  const tierEn = { diamond: "Diamond Elite", platinum: "Platinum VIP", gold: "Gold Member", prospect: "Exclusive Invitee" }[customer.tier] || "VIP Guest";
  const tierZh = { diamond: "钻石尊享会员", platinum: "铂金贵宾", gold: "金卡会员", prospect: "特邀嘉宾" }[customer.tier] || "贵宾";

  const replacements = {
    "{{CUSTOMER_NAME}}": name,
    "{{CUSTOMER_FIRST_NAME}}": firstName,
    "{{CUSTOMER_TIER}}": tier,
    "{{CUSTOMER_TIER_BADGE}}": tierEn,
    "{{CUSTOMER_TIER_BADGE_ZH}}": tierZh,
    "{{GREETING}}": greeting,
    "{{CUSTOMER_INTERESTS}}": interests,
    "{{CUSTOMER_LANGUAGE}}": customer.preferred_language || "en",
    "{{CAMPAIGN_NAME}}": campaign.campaign_name || "",
    "{{HOTEL_NAME}}": campaign.hotel_name || "Simon Casino Resort",
  };

  let result = html;
  for (const [key, value] of Object.entries(replacements)) {
    result = result.split(key).join(value);
  }
  return result;
}

function applyGenericDefaults(html, campaign) {
  return html
    .split("{{CUSTOMER_NAME}}").join("Valued Guest")
    .split("{{CUSTOMER_FIRST_NAME}}").join("Guest")
    .split("{{CUSTOMER_TIER}}").join("VIP")
    .split("{{CUSTOMER_TIER_BADGE}}").join("Honored Guest")
    .split("{{CUSTOMER_TIER_BADGE_ZH}}").join("尊贵来宾")
    .split("{{GREETING}}").join("Your Exclusive Experience Awaits")
    .split("{{CUSTOMER_INTERESTS}}").join("")
    .split("{{CUSTOMER_LANGUAGE}}").join("en")
    .split("{{CAMPAIGN_NAME}}").join(campaign.campaign_name || "")
    .split("{{HOTEL_NAME}}").join(campaign.hotel_name || "Simon Casino Resort");
}

app.get("/healthz", (req, res) => {
  res.json({ status: "healthy", service: "Campaign Landing" });
});

app.get("/readyz", (req, res) => {
  const template = loadFile(TEMPLATE_PATH);
  res.json({ status: template ? "ready" : "not ready" });
});

app.get("/", async (req, res) => {
  const template = loadFile(TEMPLATE_PATH);
  if (!template) {
    return res.status(503).send("Landing page not yet configured");
  }

  const campaign = getCampaign();
  const customerId = req.query.c;

  res.setHeader("Content-Type", "text/html");
  res.setHeader("X-Frame-Options", "");
  res.setHeader("Content-Security-Policy", "");

  if (!customerId) {
    return res.send(applyGenericDefaults(template, campaign));
  }

  const customer = await fetchCustomerFromMCP(customerId);

  if (!customer) {
    return res.send(applyGenericDefaults(template, campaign));
  }

  res.send(personalize(template, customer, campaign));
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`[Campaign Landing] Serving on 0.0.0.0:${PORT}`);
  console.log(`[Campaign Landing] Template: ${TEMPLATE_PATH}`);
  console.log(`[Campaign Landing] MongoDB MCP: ${MONGODB_MCP_URL}`);
});
