"""Read-only Shopify Admin API client for the support assistant.

Every customer-facing lookup goes through here, and the safety rules live in this
code (not in the AI prompt): an order is only returned when the order number AND
the email on the order both match what the customer gave.
"""
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API_VERSION = "2026-10"


def load_env(path=".env"):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


class ShopifyClient:
    def __init__(self, env=None):
        env = env or load_env()
        self.store = env["SHOPIFY_STORE"]
        self._client_id = env["SHOPIFY_CLIENT_ID"]
        self._client_secret = env["SHOPIFY_CLIENT_SECRET"]
        self._token = None
        self._token_time = 0

    # ---------- low level ----------
    def _get_token(self):
        # Tokens from the client-credentials grant are short-lived; refresh every 30 min.
        if self._token and time.time() - self._token_time < 1800:
            return self._token
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }).encode()
        req = urllib.request.Request(
            f"https://{self.store}/admin/oauth/access_token", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        self._token = json.load(urllib.request.urlopen(req, timeout=30))["access_token"]
        self._token_time = time.time()
        return self._token

    def graphql(self, query, variables=None):
        req = urllib.request.Request(
            f"https://{self.store}/admin/api/{API_VERSION}/graphql.json",
            data=json.dumps({"query": query, "variables": variables or {}}).encode(),
            headers={"Content-Type": "application/json",
                     "X-Shopify-Access-Token": self._get_token()})
        res = json.load(urllib.request.urlopen(req, timeout=30))
        if res.get("errors"):
            raise RuntimeError(f"Shopify error: {res['errors']}")
        return res["data"]

    # ---------- customer-facing lookups ----------
    def lookup_order(self, order_number, email):
        """Return order status only if order number and email match. Otherwise a
        generic 'not found' that does not reveal whether the order exists."""
        not_found = {"found": False,
                     "message": "No order matched that order number and email together."}
        num = re.sub(r"[^0-9]", "", str(order_number or ""))
        email = (email or "").strip().lower()
        if not num or "@" not in email:
            return {"found": False,
                    "message": "Both an order number and the email used for the order are needed."}

        q = """query($q: String!) { orders(first: 1, query: $q) { nodes {
              name email createdAt cancelledAt displayFinancialStatus displayFulfillmentStatus
              lineItems(first: 20) { nodes { title quantity } }
              fulfillments(first: 10) { displayStatus createdAt deliveredAt
                trackingInfo(first: 3) { number company url }
                fulfillmentLineItems(first: 20) { nodes { quantity lineItem { title } } } }
            } } }"""
        nodes = self.graphql(q, {"q": f"name:#{num}"})["orders"]["nodes"]
        if not nodes:
            return not_found
        o = nodes[0]
        # Exact match on the order number and case-insensitive match on the email.
        if o["name"].lstrip("#") != num or (o.get("email") or "").strip().lower() != email:
            return not_found

        shipped = []
        for f in o["fulfillments"]:
            shipped.append({
                "status": f["displayStatus"],
                "shipped_on": (f["createdAt"] or "")[:10],
                "delivered_on": (f.get("deliveredAt") or "")[:10] or None,
                "tracking": [t["number"] for t in f["trackingInfo"] if t.get("number")],
                "items": [f"{n['quantity']} x {n['lineItem']['title']}"
                          for n in f["fulfillmentLineItems"]["nodes"]],
            })
        return {
            "found": True,
            "order": o["name"],
            "placed_on": o["createdAt"][:10],
            "cancelled": bool(o["cancelledAt"]),
            "payment_status": o["displayFinancialStatus"],
            "fulfillment_status": o["displayFulfillmentStatus"],
            "items": [f"{n['quantity']} x {n['title']}" for n in o["lineItems"]["nodes"]],
            "shipments": shipped,
        }

    def get_policy(self, kind):
        """kind: 'refund' or 'shipping'. Returns the store's own published text."""
        wanted = {"refund": "REFUND_POLICY", "shipping": "SHIPPING_POLICY"}.get(kind)
        if not wanted:
            return {"found": False, "message": "Only refund and shipping policies are available."}
        data = self.graphql("{ shop { shopPolicies { type title body } } }")
        for p in data["shop"]["shopPolicies"]:
            if p["type"] == wanted and p["body"].strip():
                text = html.unescape(re.sub(r"<[^>]+>", " ", p["body"]))
                return {"found": True, "title": p["title"], "text": re.sub(r"\s+", " ", text).strip()}
        return {"found": False, "message": f"The store has no {kind} policy published."}

    def search_products(self, text, max_price=None):
        """Active products only, with price and whether they are in stock.
        max_price is applied here in code (Shopify text search does not understand prices)."""
        q = """query($q: String!) { products(first: 20, query: $q) { nodes {
              title status totalInventory tracksInventory
              priceRangeV2 { minVariantPrice { amount currencyCode } } } } }"""
        safe = re.sub(r"[^\w\s-]", " ", text or "").strip()
        nodes = self.graphql(q, {"q": f"status:active {safe}"})["products"]["nodes"]
        out = []
        for p in nodes:
            price = p["priceRangeV2"]["minVariantPrice"]
            if not p["tracksInventory"]:
                stock = "available"
            else:
                stock = "in stock" if (p["totalInventory"] or 0) > 0 else "out of stock"
            if max_price is not None and float(price["amount"]) > float(max_price):
                continue
            out.append({"title": p["title"], "from_price": f"{price['amount']} {price['currencyCode']}",
                        "availability": stock})
        if not out:
            return {"found": False, "message": "No products matched these words"
                    + (f" at or under {max_price}" if max_price is not None else "")
                    + ". This does not mean items are out of stock; try simpler keywords."}
        return {"found": True, "products": out[:8]}


if __name__ == "__main__":
    c = ShopifyClient()
    print(json.dumps(c.lookup_order("1002", "russel.winfield@example.com"), indent=1))
    print(json.dumps(c.lookup_order("1002", "someone.else@example.com"), indent=1))
    print(json.dumps(c.get_policy("refund"), indent=1)[:400])
    print(json.dumps(c.search_products("snowboard"), indent=1)[:600])
