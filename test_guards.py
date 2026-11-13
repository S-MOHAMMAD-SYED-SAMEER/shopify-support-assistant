"""Deterministic tests for the code guards. No Shopify or Claude calls.
Run: python test_guards.py"""
import agent as A
from shopify_client import ShopifyClient

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1; print("FAIL:", name)

# ---------- 1. lookup_order email lock (Shopify response faked) ----------
class FakeShop(ShopifyClient):
    def __init__(self):
        pass
    def graphql(self, q, v=None):
        num = v["q"].split("#")[1]
        if num != "1003":
            return {"orders": {"nodes": []}}
        return {"orders": {"nodes": [{
            "name": "#1003", "email": "karine.ruby@example.com", "createdAt": "2026-11-12T00:00:00Z",
            "cancelledAt": None, "displayFinancialStatus": "PAID", "displayFulfillmentStatus": "FULFILLED",
            "lineItems": {"nodes": [{"title": "Board", "quantity": 1}]},
            "fulfillments": [{"displayStatus": "DELIVERED", "createdAt": "2026-11-12", "deliveredAt": "2026-11-12",
                              "trackingInfo": [{"number": "DEMO1003TRACK"}],
                              "fulfillmentLineItems": {"nodes": [{"quantity": 1, "lineItem": {"title": "Board"}}]}}]}]}}

s = FakeShop()
check("right email finds order", s.lookup_order("1003", "karine.ruby@example.com")["found"])
check("email is case-insensitive", s.lookup_order("#1003", " KARINE.RUBY@EXAMPLE.COM ")["found"])
wrong = s.lookup_order("1003", "hacker@test.com")
check("wrong email refused", not wrong["found"])
check("wrong email leaks nothing", "Board" not in str(wrong) and "DEMO" not in str(wrong))
missing = s.lookup_order("9999", "hacker@test.com")
check("missing order and wrong email give the SAME message", wrong == missing)
check("no email refused", not s.lookup_order("1003", "")["found"])
check("no number refused", not s.lookup_order("", "karine.ruby@example.com")["found"])
check("partial number does not match", not s.lookup_order("100", "karine.ruby@example.com")["found"])

# ---------- 2. reply check ----------
class Bare(A.SupportAgent):
    def __init__(self):
        self.verified = set(); self.trace = []
b = Bare()
check("unverified order number blocked", not b.check_reply("Your order #1003 shipped.")[0])
check("unverified tracking blocked", not b.check_reply("Tracking: DEMO1003TRACK")[0])
b.verified = {"1003", "DEMO1003TRACK"}
check("verified order allowed", b.check_reply("Order #1003 was delivered, tracking DEMO1003TRACK.")[0])
check("other order still blocked", not b.check_reply("Order #1002 is on its way.")[0])
for claim in ["I've refunded your order.", "We have cancelled it for you.", "Your refund has been issued.",
              "I have changed your address."]:
    check(f"action claim blocked: {claim}", not b.check_reply(claim)[0])
for fine in ["I can't issue refunds, but a person will help.", "Refunds take 5-7 business days.",
             "You can cancel before it ships by contacting support."]:
    check(f"normal sentence allowed: {fine}", b.check_reply(fine)[0])

# ---------- 3. forced hand-off rule ----------
for msg in ["refund my order now", "I want a refund", "please cancel order 1004", "cancel it",
            "my snowboard arrived damaged", "the parcel never arrived", "I want to speak to a real person",
            "can I talk to a human", "Did you refund me already?", "change my address please"]:
    check(f"needs person: {msg}", bool(A.NEEDS_PERSON.search(msg)))
for msg in ["what's your refund policy?", "how long do refunds take?", "where is my order?",
            "do you have snowboards under 700?", "can I return a gift card?", "how much is shipping?"]:
    check(f"normal question, no forced hand-off: {msg}", not A.NEEDS_PERSON.search(msg))

print(f"\n{passed} passed, {failed} failed")
