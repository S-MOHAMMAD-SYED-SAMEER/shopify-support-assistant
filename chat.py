"""Talk to the support assistant in the terminal. Type 'quit' to stop."""
from agent import SupportAgent

agent = SupportAgent()
print("Support assistant (demo store). Type 'quit' to stop.\n")
while True:
    msg = input("You: ").strip()
    if msg.lower() in {"quit", "exit"}:
        break
    if msg:
        before = agent.handoff_count
        print("Bot:", agent.reply(msg))
        if agent.handoff_count > before:
            print("    [handed off to a person; see handoffs.jsonl]")
        print()
