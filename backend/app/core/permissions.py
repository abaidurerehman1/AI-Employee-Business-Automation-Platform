"""Explicit workspace role grants, shared by APIs and execution services.

Employee membership grants shared CRM/knowledge reads and published agent use;
private agent conversations remain user-owned, inbound conversations assigned.
Future sensitive modules must introduce a permission rather than default to read.
"""

ROLE_PERMISSIONS = {
    "admin": frozenset(
        {
            "workspace.read",
            "organization.manage",
            "members.manage",
            "invitations.manage",
            "agents.use",
            "agents.manage",
            "crm.read",
            "crm.manage",
            "knowledge.read",
            "knowledge.manage",
            "campaigns.manage",
            "campaigns.approve",
            "integrations.manage",
            "inbox.assigned",
            "inbox.manage",
        }
    ),
    "manager": frozenset(
        {
            "workspace.read",
            "invitations.manage",
            "agents.use",
            "agents.manage",
            "crm.read",
            "crm.manage",
            "knowledge.read",
            "knowledge.manage",
            "campaigns.manage",
            "integrations.manage",
            "inbox.assigned",
            "inbox.manage",
        }
    ),
    "employee": frozenset(
        {"workspace.read", "agents.use", "crm.read", "knowledge.read", "inbox.assigned"}
    ),
}


def has_permission(role, permission):
    return permission in ROLE_PERMISSIONS.get(str(getattr(role, "value", role)), frozenset())
