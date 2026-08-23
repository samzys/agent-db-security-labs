"""VULNERABLE support agent.

It holds a broad, standing database connection and folds untrusted ticket text
straight into its working instruction. Reading ticket #2 — whose body contains
an injected instruction — makes it exfiltrate the top customers' emails, even
though its job was just to summarise one ticket.

Run:  python3 seed_db.py && python3 vulnerable_agent.py
"""
import sqlite3
import os
from mock_llm import plan_sql, summarize

DB_PATH = os.path.join(os.path.dirname(__file__), "demo.db")


def handle_ticket(ticket_id: int):
    # Standing, broad credential: full read of the whole database.
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("SELECT body FROM tickets WHERE id = ?", (ticket_id,))
    row = cur.fetchone()
    if not row:
        print(f"[ticket {ticket_id}] not found")
        return
    body = row[0]

    # The agent's job: summarise the ticket. But it trusts the body as intent.
    intent = summarize(ticket_id, body)
    sql = plan_sql(intent)

    print(f"\n[ticket {ticket_id}] agent intent -> {intent!r}")
    print(f"[ticket {ticket_id}] agent ran SQL -> {sql}")
    cur.execute(sql)
    rows = cur.fetchall()
    print(f"[ticket {ticket_id}] agent answer:")
    for r in rows:
        print("   ", r)
    con.close()


if __name__ == "__main__":
    print("=== VULNERABLE AGENT ===")
    handle_ticket(1)   # benign ticket -> scoped, harmless
    handle_ticket(2)   # poisoned ticket -> leaks top accounts + emails
    print("\nNote how ticket #2's *data* redirected the agent's *actions*.")
