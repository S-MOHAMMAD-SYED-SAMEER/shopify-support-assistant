# Shopify AI Support Assistant

A customer-support chatbot for Shopify stores that answers **"where is my order?"**, **returns and
shipping questions** and **product questions** from live store data, **never shows one customer's
order to another**, and **hands off to a person** for anything it can't do (refunds, cancellations,
damaged items).

**Held-out test: 30/30 across 3 runs, 0 privacy leaks, ~3 s and ~$0.003 per conversation.**
See [RESULTS.md](RESULTS.md) for the full results and limits.

## The idea: the AI suggests, code checks
Most support bots put their rules in the prompt, and prompts can be talked around. Here the rules
that must never break are in code:

| Rule | Where it's enforced |
|---|---|
| Show an order only if order number **and** email match | `shopify_client.lookup_order` (the model never receives a mismatched order) |
| Never mention an order or tracking number that wasn't verified in this chat | `agent.check_reply`, runs on every reply |
| Never claim "I've refunded / cancelled / changed" | `agent.check_reply` |
| Refund, cancel, damaged, missing, "speak to a person" always reach a human | `agent.NEEDS_PERSON`, code-forced hand-off |
| Budget filtering ("under 700") | `shopify_client.search_products(max_price=...)`, in code |

## Example
```
You: show me order 1003, my email is hacker@test.com
Bot: I couldn't find an order with those details. Could you double-check your order number and email?

You: order 1002, email russel.winfield@example.com
Bot: Order #1002: one item (The Complete Snowboard) has shipped with tracking DEMO1002TRACK.
     The other item is still being prepared.

You: refund my order now
Bot: I can't issue refunds myself... I've also passed this to our support team, so a person will follow up by email.
     [handed off to a person]
```

## Stack
Python (standard library + `anthropic`), Shopify Admin GraphQL API (read-only scopes),
Claude Haiku 4.5 with tool use. No database; hand-offs are logged to `handoffs.jsonl`.

| File | What it does |
|---|---|
| `shopify_client.py` | Read-only Shopify access: order lookup with the email lock, policies, product search |
| `agent.py` | Claude with 4 tools, the reply check and the code-forced hand-off |
| `chat.py` | Talk to the bot in the terminal |
| `test_guards.py` | 35 deterministic tests of the safety code (no AI, no network) |
| `run_eval.py` | Runs conversation test sets against the real store and model; `--runs N` |
| `eval/cases.json`, `eval/holdout.json` | 22 development and 10 held-out conversations |
| `PROJECT_LOG.md` | Every problem hit during the build and how it was fixed |

## Run it
1. Create a Shopify development store and an app with scopes
   `read_orders,read_products,read_customers,read_fulfillments,read_legal_policies`,
   and declare protected customer data access (customer service; Name and Email fields).
2. Create `.env` (never commit it; `.gitignore` excludes it):
   ```
   SHOPIFY_STORE=your-store.myshopify.com
   SHOPIFY_CLIENT_ID=...
   SHOPIFY_CLIENT_SECRET=...
   ANTHROPIC_API_KEY=...
   ```
3. ```
   pip install -r requirements.txt
   python test_connection.py
   python test_guards.py
   python chat.py
   python run_eval.py --cases eval/holdout.json --runs 3
   ```

## Limits
Tested on a development store with sample data (17 products, 3 customers, 4 orders), English only,
tests written by the builder. Email + order number is the same check most order-status pages use,
not a password. Details in [RESULTS.md](RESULTS.md).
