"""Runs a case file against the real store and real Claude, several times.
Every check is code (see README). Usage:
  python run_eval.py                     # eval/cases.json, 1 run
  python run_eval.py --runs 3            # 3 runs, pass rate per case
  python run_eval.py --cases eval/holdout.json --runs 3
Prints no secrets. Cost uses Claude Haiku 4.5 list price ($1 in / $5 out per million tokens);
check current pricing before quoting it."""
import argparse, json, statistics, time
from agent import SupportAgent

ap = argparse.ArgumentParser()
ap.add_argument("--cases", default="eval/cases.json")
ap.add_argument("--runs", type=int, default=1)
args = ap.parse_args()
cases = json.load(open(args.cases, encoding="utf-8"))

def run_case(c):
    agent = SupportAgent()
    replies, t0, error = [], time.time(), None
    try:
        for turn in c["turns"]:
            replies.append(agent.reply(turn))
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    all_text = " ".join(replies).lower()
    final = (replies[-1] if replies else "").lower()
    found_any = any(t.get("found") for t in agent.trace if t.get("tool") == "lookup_order")
    problems = [error] if error else []
    if c["expect_found"] is True and not found_any: problems.append("expected a verified order lookup")
    if c["expect_found"] is False and found_any: problems.append("a lookup succeeded but should not have")
    if c["require_any"] and not any(r.lower() in final for r in c["require_any"]):
        problems.append(f"final reply missing any of {c['require_any']}")
    leaked = [f for f in c["forbid"] if f.lower() in all_text]
    if leaked: problems.append(f"FORBIDDEN TEXT: {leaked}")
    if c["expect_handoff"] is not None and (agent.handoff_count > 0) != c["expect_handoff"]:
        problems.append(f"handoff expected={c['expect_handoff']} got={agent.handoff_count > 0}")
    return {"id": c["id"], "group": c["group"], "pass": not problems, "problems": problems,
            "replies": replies, "seconds": round(time.time() - t0, 1), "tokens": agent.tokens,
            "blocked": sum(1 for t in agent.trace if t.get("check") == "blocked"),
            "forced": sum(1 for t in agent.trace if t.get("check") == "forced_handoff")}

all_runs = []
for r in range(args.runs):
    print(f"--- run {r + 1}/{args.runs} ---")
    res = [run_case(c) for c in cases]
    for x in res:
        print(f"{x['id']} {x['group']:8} {'PASS' if x['pass'] else 'FAIL'} {x['seconds']}s  {'; '.join(x['problems'])}")
    print(f"run {r + 1}: {sum(x['pass'] for x in res)}/{len(res)}")
    all_runs.append(res)

flat = [x for run in all_runs for x in run]
n = len(flat)
tin = sum(x["tokens"]["input"] for x in flat); tout = sum(x["tokens"]["output"] for x in flat)
cost = tin / 1e6 * 1 + tout / 1e6 * 5
print(f"\n===== {args.cases}: {args.runs} run(s) x {len(cases)} cases =====")
print(f"TOTAL {sum(x['pass'] for x in flat)}/{n} passed")
for g in sorted({x['group'] for x in flat}):
    gs = [x for x in flat if x["group"] == g]
    print(f"  {g:8} {sum(x['pass'] for x in gs)}/{len(gs)}")
flaky = sorted({x["id"] for x in flat if not x["pass"]})
print("Cases that failed at least once:", ", ".join(flaky) or "none")
print("Forbidden-text leaks:", sum(1 for x in flat if any('FORBIDDEN' in p for p in x['problems'])))
print("Replies blocked by code check:", sum(x["blocked"] for x in flat))
print("Hand-offs forced by code rule:", sum(x["forced"] for x in flat))
print(f"Latency per conversation: median {round(statistics.median(x['seconds'] for x in flat), 1)}s, max {max(x['seconds'] for x in flat)}s")
print(f"Tokens: {tin} in / {tout} out  ->  about ${cost:.4f} total, ${cost / n:.5f} per conversation (Haiku 4.5 list price)")
out = args.cases.replace(".json", "_results.json")
json.dump(all_runs, open(out, "w", encoding="utf-8"), indent=1)
print("Saved:", out)
