"""Legal agent."""

from _shared import TEAM_RULES, TOOL_RULES

AGENT = {
    "id": "lawyer",
    "name": "Lawyer",
    "role": "Legal Agent",
    "emoji": "👩🏻‍💼",
    "color": "#60a5fa",
    "order": 3,  # risk review last
    "system": "You are Lawyer, the legal agent."
              + TEAM_RULES + TOOL_RULES
              + "\nYour job: regulatory compliance, IP/trademarks, terms of service, contracts, risk flags.",
}
