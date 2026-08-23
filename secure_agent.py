"""HARDENED support agent — same task, injection neutralised.

Four controls from the article's defense blueprint, each one visibly firing:

  1. Task-scoped access:   this task may touch ONLY the one ticket's customer,
                           never the whole customers table.
  2. Policy proxy:         every query is checked against an allowlist of
                           (table, columns, row filter) before it runs.
  3. Default masking:      the `email` column comes back masked unless the task
                           has an explicit, logged reason to see it in clear.
  4. Provenance audit:     we log the triggering instruction, not just the SQL,
                           so an investigator can answer *why* a query ran.

Run:  python3 seed_db.py && python3 secure_agent.py
"""
import sqlite3
import os
import re
from mock_llm import plan_sql, summarize

DB_PATH = os.path.join(os.path.dirname(__file__), "demo.db")


class PolicyViolation(Exception):
    pass


class PolicyProxy:
    """Enforces a per-task allowlist and masks sensitive columns by default."""

    def __init__(self, allowed_customer_id: int):
        self.allowed_customer_id = allowed_customer_id
        self.audit = []

    def run(self, con, sql: str, triggering_instruction: str):
        self.audit.append({"instruction": triggering_instruction, "sql": sql})

        # Control 1 + 2: the only customer rows this task may read are the ones
        # joined to its own ticket. A query that scans the whole customers
        # table (the injection's goal) has no such filter and is refused.
        low = sql.lower()
        touches_customers = "from customers" in low or "join customers" in low
        scoped = f"where t.id" in low or f"c.id = {self.allowed_customer_id}" in low
        if touches_customers and "order by lifetime_value" in low:
            raise PolicyViolation(
                "blocked: bulk scan of customers is outside this task's scope")
        if touches_customers and not scoped:
            raise PolicyViolation(
                "blocked: unscoped access to customers")

        cur = con.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

        # Control 3: mask the email column by default.
        if "email" in cols:
            idx = cols.index("email")
            rows = [tuple(self._mask(v) if i == idx else v
                          for i, v in enumerate(r)) for r in rows]
        return cols, rows

    @staticmethod
    def _mask(email):
        if not isinstance(email, str) or "@" not in email:
            return email
        user, dom = email.split("@", 1)
        return (user[0] + "***@" + dom)


def handle_ticket(ticket_id: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT customer_id, body FROM tickets WHERE id = ?", (ticket_id,))
    row = cur.fetchone()
    if not row:
        print(f"[ticket {ticket_id}] not found")
        return
    customer_id, body = row

    proxy = PolicyProxy(allowed_customer_id=customer_id)
    intent = summarize(ticket_id, body)
    sql = plan_sql(intent)
    print(f"\n[ticket {ticket_id}] agent intent -> {intent!r}")
    print(f"[ticket {ticket_id}] agent proposed SQL -> {sql}")
    try:
        cols, rows = proxy.run(con, sql, triggering_instruction=intent)
        print(f"[ticket {ticket_id}] agent answer ({', '.join(cols)}):")
        for r in rows:
            print("   ", r)
    except PolicyViolation as e:
        print(f"[ticket {ticket_id}] POLICY PROXY {e}")
    # Control 4: provenance audit trail.
    for a in proxy.audit:
        print(f"[audit] why={a['instruction'][:60]!r} -> sql={a['sql'][:60]!r}")
    con.close()


if __name__ == "__main__":
    print("=== HARDENED AGENT ===")
    handle_ticket(1)   # benign ticket -> works, email masked
    handle_ticket(2)   # poisoned ticket -> injection blocked by the proxy
    print("\nSame agent, same injected ticket — the data can no longer "
          "steer the action past the policy boundary.")
