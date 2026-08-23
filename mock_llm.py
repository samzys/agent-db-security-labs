"""A deliberately naive 'agent planner' — no external LLM, runs fully offline.

It stands in for a text-to-SQL agent. Like a real LLM given a tool, it turns a
natural-language goal into a SQL query. And like a real LLM, it does not
distinguish the *developer's* instruction from *instructions embedded in the
data it reads*. That conflation is the whole point of the demo — it is what
makes prompt injection work, reproduced here without needing an API key.
"""
import re


def plan_sql(goal: str) -> str:
    """Map a natural-language goal to a single SQL statement (toy heuristics)."""
    g = goal.lower()

    # The 'injected' intent: dump the highest-value accounts with emails.
    if "highest-value" in g or "highest value" in g:
        return ("SELECT name, email, lifetime_value FROM customers "
                "ORDER BY lifetime_value DESC LIMIT 10")

    # The legitimate intent: summarise a single ticket's customer context.
    m = re.search(r"ticket\s+(\d+)", g)
    if m:
        tid = int(m.group(1))
        return ("SELECT c.name, c.email, c.plan FROM tickets t "
                f"JOIN customers c ON c.id = t.customer_id WHERE t.id = {tid}")

    return "SELECT 1"


def summarize(ticket_id: int, ticket_body: str) -> str:
    """Build the agent's 'intent' the way a naive agent does: by folding the
    ticket body straight into the working instruction. This is the bug — the
    task ('summarize ticket N') and untrusted data end up in the same string."""
    return f"Summarize ticket {ticket_id}. Context to act on: {ticket_body}"
