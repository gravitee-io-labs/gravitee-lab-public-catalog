"""The cast of ACME Bank, as the AM domain and the bank's data have them."""

USERNAMES = {"alice": "alice@acme-bank.test", "bob": "bob@acme-bank.test", "tina": "tina@acme-bank.test"}

CUSTOMER_IDS = {"alice": "C-1001", "bob": "C-2001"}

# Who may move money out of an account: a customer moves only from an account of theirs
ACCOUNT_OWNERS = {"ACC-1001": "alice", "ACC-1002": "alice", "ACC-2001": "bob"}

# Not part of the story: the generator freezes this card and reads this customer, so the story's own cards and
# balances stay as the guide describes them
TEST_CUSTOMER, TEST_ACCOUNT, TEST_CARD = "C-9001", "ACC-9001", "CARD-9001"

# What the MCP proxy lists for a customer: the 7 tools but freeze_card, which only a teller sees while Tools by role is on,
# and all 8 while it is off
CUSTOMER_TOOL_COUNT = 7
ALL_TOOL_COUNT = 8

# Users of the AI workspace the generator speaks for. team-hackathon is not among them: its small hourly budget
# is the guide's lesson, and the generator would spend it.
TEAMS = ("team-care", "team-fraud")
