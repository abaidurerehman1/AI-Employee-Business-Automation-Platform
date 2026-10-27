import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyArguments(ToolArguments):
    pass


class SearchContactsArguments(ToolArguments):
    query: str = Field(min_length=2, max_length=100)


class CreateContactArguments(ToolArguments):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)


class UpdateContactArguments(ToolArguments):
    contact_id: str
    name: str | None
    email: str | None
    phone: str | None


class CreateLeadArguments(ToolArguments):
    title: str = Field(min_length=1, max_length=200)


class UpdateLeadArguments(ToolArguments):
    lead_id: str
    title: str | None
    stage: str | None


class CreateCompanyArguments(ToolArguments):
    name: str = Field(min_length=1, max_length=200)


class UpdateCompanyArguments(ToolArguments):
    company_id: str
    name: str | None
    website: str | None


class CreateDealArguments(ToolArguments):
    title: str = Field(min_length=1, max_length=200)
    amount_minor: int = Field(ge=0, le=2_000_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class UpdateDealArguments(ToolArguments):
    deal_id: str
    title: str | None
    stage: str | None
    amount_minor: int | None
    currency: str | None


CRM_WRITE_TOOLS = {f"{action}_crm_{kind}" for action in ("create", "update") for kind in ("company", "contact", "lead", "deal")}


class ToolInputError(ValueError):
    pass

TOOL_REGISTRY = {
    "get_current_utc_time": {
        "name": "get_current_utc_time",
        "description": "Read the current UTC date and time.",
    },
    "search_crm_contacts": {
        "name": "search_crm_contacts",
        "description": "Search contact names in the current organization's CRM.",
    },
    "search_crm_leads": {
        "name": "search_crm_leads",
        "description": "Search lead titles in the current organization's CRM.",
    },
    "search_crm_companies": {"name": "search_crm_companies", "description": "Search company names in the current organization's CRM."},
    "search_crm_deals": {"name": "search_crm_deals", "description": "Search deal titles in the current organization's CRM."},
    "create_crm_contact": {"name": "create_crm_contact", "description": "Create a CRM contact with name and email."},
    "update_crm_contact": {"name": "update_crm_contact", "description": "Update a CRM contact by ID. Use null for fields to leave unchanged."},
    "create_crm_lead": {"name": "create_crm_lead", "description": "Create a new CRM lead by title."},
    "update_crm_lead": {"name": "update_crm_lead", "description": "Update a CRM lead by ID. Use null for fields to leave unchanged. Stages: new, contacted, qualified, proposal, won, lost."},
    "create_crm_company": {"name": "create_crm_company", "description": "Create a CRM company by name."},
    "update_crm_company": {"name": "update_crm_company", "description": "Update a CRM company by ID. Use null for unchanged fields."},
    "create_crm_deal": {"name": "create_crm_deal", "description": "Create a CRM deal with an amount in minor currency units and a three-letter currency."},
    "update_crm_deal": {"name": "update_crm_deal", "description": "Update a CRM deal by ID. Use null for unchanged fields. Stages: open, negotiation, won, lost."},
}
TOOL_ARGUMENT_MODELS: dict[str, type[ToolArguments]] = {
    "get_current_utc_time": EmptyArguments,
    "search_crm_contacts": SearchContactsArguments,
    "search_crm_leads": SearchContactsArguments,
    "search_crm_companies": SearchContactsArguments,
    "search_crm_deals": SearchContactsArguments,
    "create_crm_contact": CreateContactArguments,
    "update_crm_contact": UpdateContactArguments,
    "create_crm_lead": CreateLeadArguments,
    "update_crm_lead": UpdateLeadArguments,
    "create_crm_company": CreateCompanyArguments,
    "update_crm_company": UpdateCompanyArguments,
    "create_crm_deal": CreateDealArguments,
    "update_crm_deal": UpdateDealArguments,
}


def get_tool_schemas(names: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            **TOOL_REGISTRY[name],
            "parameters": TOOL_ARGUMENT_MODELS[name].model_json_schema(),
            "strict": True,
        }
        for name in names
        if name in TOOL_REGISTRY
    ]


def validate_tool_arguments(name: str, raw_arguments: str) -> dict[str, Any]:
    if name not in TOOL_ARGUMENT_MODELS:
        raise ToolInputError("Unknown tool")
    try:
        arguments = json.loads(raw_arguments)
        if not isinstance(arguments, dict):
            raise ToolInputError("Tool arguments must be a JSON object")
        return TOOL_ARGUMENT_MODELS[name].model_validate(arguments).model_dump(mode="json")
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ToolInputError("Tool arguments do not match the tool schema") from exc


def execute_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
) -> str:
    del idempotency_key
    if name == "get_current_utc_time":
        validate_tool_arguments(name, json.dumps(arguments or {}))
        return datetime.now(UTC).isoformat()
    raise ValueError("Unknown tool")
