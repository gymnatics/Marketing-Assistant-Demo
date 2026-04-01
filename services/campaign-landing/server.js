const express = require("express");
const fs = require("fs");
const path = require("path");

const app = express();
const PORT = process.env.PORT || 8080;

const DATA_DIR = process.env.DATA_DIR || "/data";
const TEMPLATE_PATH = `${DATA_DIR}/template.html`;
const CUSTOMERS_PATH = `${DATA_DIR}/customers.json`;
const CAMPAIGN_PATH = `${DATA_DIR}/campaign.json`;

function loadFile(filePath) {
  try {
    return fs.readFileSync(filePath, "utf-8");
  } catch {
    return null;
  }
}

function getCustomers() {
  const raw = loadFile(CUSTOMERS_PATH);
  if (!raw) return {};
  try {
    const list = JSON.parse(raw);
    const map = {};
    for (const c of list) {
      map[c.customer_id] = c;
    }
    return map;
  } catch {
    return {};
  }
}

function getCampaign() {
  const raw = loadFile(CAMPAIGN_PATH);
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function personalize(html, customer, campaign) {
  const lang = customer.preferred_language || "en";
  const isZh = lang.startsWith("zh");

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
    "{{CUSTOMER_LANGUAGE}}": lang,
    "{{CAMPAIGN_NAME}}": campaign.campaign_name || "",
    "{{HOTEL_NAME}}": campaign.hotel_name || "Simon Casino Resort",
  };

  let result = html;
  for (const [key, value] of Object.entries(replacements)) {
    result = result.split(key).join(value);
  }
  return result;
}

app.get("/healthz", (req, res) => {
  res.json({ status: "healthy", service: "Campaign Landing" });
});

app.get("/readyz", (req, res) => {
  const template = loadFile(TEMPLATE_PATH);
  res.json({ status: template ? "ready" : "not ready" });
});

app.get("/", (req, res) => {
  const template = loadFile(TEMPLATE_PATH);
  if (!template) {
    return res.status(503).send("Landing page not yet configured");
  }

  const customerId = req.query.c;

  if (!customerId) {
    const genericHtml = template
      .split("{{CUSTOMER_NAME}}").join("Valued Guest")
      .split("{{CUSTOMER_FIRST_NAME}}").join("Guest")
      .split("{{CUSTOMER_TIER}}").join("VIP")
      .split("{{CUSTOMER_TIER_BADGE}}").join("Honored Guest")
      .split("{{CUSTOMER_TIER_BADGE_ZH}}").join("尊贵来宾")
      .split("{{GREETING}}").join("Your Exclusive Experience Awaits")
      .split("{{CUSTOMER_INTERESTS}}").join("")
      .split("{{CUSTOMER_LANGUAGE}}").join("en")
      .split("{{CAMPAIGN_NAME}}").join("")
      .split("{{HOTEL_NAME}}").join("Simon Casino Resort");
    res.setHeader("Content-Type", "text/html");
    res.setHeader("X-Frame-Options", "");
    res.setHeader("Content-Security-Policy", "");
    return res.send(genericHtml);
  }

  const customers = getCustomers();
  const campaign = getCampaign();
  const customer = customers[customerId];

  if (!customer) {
    const genericHtml = template
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
    res.setHeader("Content-Type", "text/html");
    res.setHeader("X-Frame-Options", "");
    res.setHeader("Content-Security-Policy", "");
    return res.send(genericHtml);
  }

  const personalizedHtml = personalize(template, customer, campaign);

  res.setHeader("Content-Type", "text/html");
  res.setHeader("X-Frame-Options", "");
  res.setHeader("Content-Security-Policy", "");
  res.send(personalizedHtml);
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`[Campaign Landing] Serving on 0.0.0.0:${PORT}`);
  console.log(`[Campaign Landing] Template: ${TEMPLATE_PATH}`);
  console.log(`[Campaign Landing] Customers: ${CUSTOMERS_PATH}`);
});
