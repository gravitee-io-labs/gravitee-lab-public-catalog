"""The cast of ACME Bank (the same people as in the AM domain) and the accounts each of them has."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    role: str
    username: str
    send_from: str
    send_to: str
    send_amount: int
    customer_id: str | None = None
    accounts: tuple[str, ...] = ()

    @property
    def first(self) -> str:
        """The first name: what a hop of Behind the answer calls the person ("Alice asked Ace")."""
        return self.name.split()[0]


PERSONAS = {p.id: p for p in (
    Persona("alice", "Alice Martin", "customer", "alice@acme-bank.test", "ACC-1001", "ACC-2001", 600, "C-1001", ("ACC-1001", "ACC-1002")),
    Persona("bob", "Bob Chen", "customer", "bob@acme-bank.test", "ACC-2001", "ACC-1001", 50, "C-2001", ("ACC-2001",)),
    Persona("tina", "Tina Torres", "teller", "tina@acme-bank.test", "ACC-1001", "ACC-2001", 50),
)}


def by_username(username) -> Persona | None:
    """The person of an Access Management user name, None for any other account of the domain."""
    return next((p for p in PERSONAS.values() if p.username == username), None) if isinstance(username, str) else None


# (user of the AI workspace, label). team-hackathon first: its small hourly budget tells the whole spend story.
TEAMS = (("team-hackathon", "Hackathon sandbox"), ("team-care", "Customer care"), ("team-fraud", "Fraud analytics"))


def describe(persona: Persona) -> dict:
    return {"id": persona.id, "name": persona.name, "role": persona.role, "customer_id": persona.customer_id,
            "accounts": list(persona.accounts),
            "send": {"from": persona.send_from, "to": persona.send_to, "amount": persona.send_amount}}
