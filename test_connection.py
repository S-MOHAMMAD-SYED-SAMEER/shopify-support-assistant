"""Checks the Shopify app credentials in .env. Prints no secrets."""
import json, urllib.request, urllib.parse, urllib.error

env = {}
for line in open(".env", encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

store = env["SHOPIFY_STORE"]
data = urllib.parse.urlencode({
    "grant_type": "client_credentials",
    "client_id": env["SHOPIFY_CLIENT_ID"],
    "client_secret": env["SHOPIFY_CLIENT_SECRET"],
}).encode()

try:
    req = urllib.request.Request(f"https://{store}/admin/oauth/access_token", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    tok = json.load(urllib.request.urlopen(req, timeout=30))
    print("1. Token: OK")
    print("   Scopes:", tok.get("scope"))

    query = """{ shop { name }
      orders(first: 10) { nodes { name displayFinancialStatus displayFulfillmentStatus
        customer { displayName } } }
      products(first: 3) { nodes { title totalInventory } } }"""
    req2 = urllib.request.Request(f"https://{store}/admin/api/2026-10/graphql.json",
                                  data=json.dumps({"query": query}).encode(),
                                  headers={"Content-Type": "application/json",
                                           "X-Shopify-Access-Token": tok["access_token"]})
    res = json.load(urllib.request.urlopen(req2, timeout=30))
    if res.get("errors"):
        print("2. Query errors:", res["errors"])
    else:
        d = res["data"]
        print("2. Store:", d["shop"]["name"])
        for o in d["orders"]["nodes"]:
            c = (o.get("customer") or {}).get("displayName", "-")
            print(f"   {o['name']}: {o['displayFinancialStatus']} / {o['displayFulfillmentStatus']} / {c}")
        for p in d["products"]["nodes"]:
            print(f"   product: {p['title']} (stock {p['totalInventory']})")
        print("ALL GOOD")
except urllib.error.HTTPError as e:
    body = e.read().decode(errors="replace"); import re as _re; m = _re.findall(r"<(?:p|h1|h2)[^>]*>(.*?)</(?:p|h1|h2)>", body, _re.S); print("FAILED: HTTP", e.code, " | ".join(_re.sub(r"<[^>]+>|\s+", " ", x).strip() for x in m)[:500])
except Exception as e:
    print("FAILED:", type(e).__name__, e)
