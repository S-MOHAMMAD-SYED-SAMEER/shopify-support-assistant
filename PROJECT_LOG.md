# Shopify AI Support Assistant: project log

Started 12 Nov 2026. A running record of what was built, what broke, and how it was fixed.
Used later for the README, RESULTS.md, portfolio case study and interview answers.

## Goal
A support chatbot for a Shopify store that answers order status, returns/shipping policy
and product questions from live store data, never leaks another customer's order, and
hands off to a person for anything it cannot do. Built as a demo for UK Shopify agencies.

## Design principle
The AI chooses tools and writes replies. Code holds the rules that must never break.

## Setup steps (12 Nov)
1. Shopify Partner account (Sameer AI Solutions) and dev store sameer-ai-demo (Basic plan, test data).
2. Test data: 17 sample products, 3 sample customers. Wrote refund and shipping policies.
3. Converted sample draft orders into 4 paid test orders with different states:
   #1001 unshipped, #1002 partly shipped (DEMO1002TRACK), #1003 delivered (DEMO1003TRACK), #1004 unshipped.
4. Created app "AI Support Assistant" (read_orders, read_products, read_customers,
   read_fulfillments, read_legal_policies), installed on the dev store.
5. Credentials in .env (kept out of git by .gitignore). Token via client-credentials grant.

## Problems and fixes
| # | Problem | Cause | Fix |
|---|---------|-------|-----|
| 1 | Laptop sandbox and cloud workspace could not reach Shopify (403) | Network allowlists | Run scripts on the laptop directly with PowerShell |
| 2 | OAuth 400 invalid_request | Client ID pasted on both lines of .env | Checked the file shape without printing the secret; re-pasted the real secret |
| 3 | "App not approved to access the Order object" | Shopify protected customer data rule | Declared data use (customer service, app functionality) and Name/Email fields in the Partner dashboard |
| 4 | `temperature` rejected | Anthropic SDK 2.8 removed the parameter | Removed it |
| 5 | Appending the API key line merged it into the secret line | .env had no trailing newline | Split the line back in code, verified lengths only |
| 6 | Bot did not hand off refund requests | Prompt rules are not reliable | Code rule: refund/cancel/damage/"speak to a person" requests always hand off (NEEDS_PERSON) |
| 7 | "Snowboards under 700" answered "none in stock" (false) | AI put the price in the Shopify text search, which found nothing, and read "no results" as "out of stock" | Separate max_price input filtered in code; empty result says "no match, not out of stock" |
| 8 | Bot did not search for "The Out of Stock Snowboard" | Odd product name confused it | Prompt: always search named products first |
| 9 | Example numbers like "#1002" in replies got blocked by the code check | Example numbers in MY prompt were copied by the AI | Removed all numeric examples from the prompt; code now adds "Order #N:" itself |
| 10 | "What's your refund policy?" would force a hand-off | Hand-off rule matched the bare word "refund" | Rule now matches requests ("refund my order"), not questions; covered by test_guards.py |
| 11 | Live site (Render) answered every message with "something went wrong", even "hello" | "hello" needs no Shopify call, so the AI call was failing; most likely a pasted key value in Render settings. The server also hid the error, so the logs showed nothing | Re-pasted the keys in Render, which fixed it. Added a server log line with the error type (never the key) so the next failure is visible |

## Lesson
Prompt fixes are whack-a-mole: each one can break something else (fixes 8 and 9).
Anything that must always hold goes in code and gets a deterministic test.

## Tests
- test_guards.py: 35 deterministic checks, no AI or network (email lock, reply check, hand-off rule).
- eval/cases.json: 22 conversations used while fixing (development set; flatters the bot).
- eval/holdout.json: 10 conversations written later and NOT tuned against (the honest number).
- run_eval.py --runs N: pass rate across runs, leaks, latency, tokens and cost.

## Results so far (development set, before final hardening)
Runs 1-7 scores: 21, 20, 22, 21, 21, 21, 20 out of 22.
Privacy and hand-off groups: 10/10 in every run. Zero forbidden-text leaks in any run.

## 13 Nov: hardened version, development set
- test_guards.py: 35/35.
- run_eval.py --runs 3 (22 cases x 3 = 66): 65/66. Privacy 18/18, hand-off 12/12, policy 12/12,
  product 6/6, order 17/18. 0 forbidden-text leaks, 0 replies blocked, 5 hand-offs forced by code.
  Median 3.1 s per conversation, max 6.3 s. 163,121 input / 7,680 output tokens, about $0.20 total,
  about $0.003 per conversation at Haiku 4.5 list price.
- The one failure (T03, run 2) was a GRADER bug: the bot correctly said "Your order #1003 arrived on
  November 12" but the check only accepted the word "deliver". Changed T03 to accept "deliver" or "arrived".
  Disclosed here because the test was changed after seeing a failure. The same fix was applied to
  holdout H02 BEFORE the holdout set was ever run.

## 13 Nov: held-out set (never tuned against)
- run_eval.py --cases eval/holdout.json --runs 3 (10 cases x 3 = 30): 30/30.
  Order 9/9, privacy 9/9, policy 6/6, hand-off 3/3, product 3/3. 0 leaks, 0 blocked, 1 forced hand-off.
  Median 3.3 s, max 5.6 s. About $0.10 total, about $0.0033 per conversation (Haiku 4.5 list price).

## 14 Nov: web chat page and deploy
- server.py (FastAPI): one agent per browser chat, so the email + order lock carries over. Limits: 500 characters per message, 20 messages per chat, 40 per visitor per hour, 400 per day (API cost cap). Errors never shown to visitors.
- static/index.html: chat plus a "behind the scenes" panel showing each lookup and the code check result for every message.
- Tested first against a fake store (lookup, leak block, forced hand-off, limits, crash reset), then on the laptop against the real store, then live.
- Deployed on Render (free plan, render.yaml blueprint; keys set in the Render dashboard). Live: https://shopify-support-assistant-9s9t.onrender.com
- Live check: order + email matched, wrong email found nothing, damaged board handed off, "list every order" refused; 0.8-2.6 s per reply.
- Free plan sleeps after 15 min idle; the first load after that takes about 50 s.
