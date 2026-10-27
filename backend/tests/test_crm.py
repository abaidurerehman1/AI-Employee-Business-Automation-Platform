import io
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from tests.test_auth import login, register_and_verify


def account(client, email, organization):
    register_and_verify(client, email, organization)
    session = login(client, email)
    return {"X-Organization-ID": session["organizations"][0]["id"], "X-CSRF-Token": session["csrf_token"]}


def test_crm_lifecycle_and_isolation(client: TestClient):
    headers = account(client, "crm-owner@example.com", "First CRM")
    company = client.post("/api/v1/crm/companies", headers=headers, json={"name": " Acme "})
    assert company.status_code == 201, company.text
    assert client.post("/api/v1/crm/companies", headers=headers, json={"name": "ACME"}).status_code == 409
    contact = client.post("/api/v1/crm/contacts", headers=headers, json={"name": "Jane", "email": "JANE@EXAMPLE.COM", "company_id": company.json()["id"]})
    assert contact.status_code == 201, contact.text
    assert contact.json()["email"] == "jane@example.com"
    assert client.post("/api/v1/crm/contacts", headers=headers, json={"name": "Duplicate", "email": "jane@example.com"}).status_code == 409
    owner = login(client, "crm-owner@example.com")
    headers["X-CSRF-Token"] = owner["csrf_token"]
    lead = client.post("/api/v1/crm/leads", headers=headers, json={"title": "Jane opportunity", "stage": "qualified", "owner_id": owner["user"]["id"], "contact_id": contact.json()["id"], "company_id": company.json()["id"]})
    assert lead.status_code == 201, lead.text
    deal = client.post("/api/v1/crm/deals", headers=headers, json={"title": "Contract", "lead_id": lead.json()["id"], "amount_minor": 15000, "currency": "USD"})
    assert deal.status_code == 201, deal.text
    activity = client.post(f"/api/v1/crm/leads/{lead.json()['id']}/activities", headers=headers, json={"kind": "call", "content": "Discussed pricing"})
    assert activity.status_code == 201, activity.text
    assert len(client.get(f"/api/v1/crm/leads/{lead.json()['id']}/activities", headers=headers).json()) == 1
    found = client.get("/api/v1/crm/leads?q=Jane&stage=qualified&page_size=1", headers=headers).json()
    assert found["total"] == 1 and found["items"][0]["id"] == lead.json()["id"]
    assert client.put(f"/api/v1/crm/leads/{lead.json()['id']}", headers=headers, json={"title": "Updated", "stage": "won", "owner_id": owner["user"]["id"]}).status_code == 200
    other = account(client, "crm-other@example.com", "Second CRM")
    assert client.get(f"/api/v1/crm/contacts/{contact.json()['id']}", headers=other).status_code == 404
    assert client.post("/api/v1/crm/leads", headers=other, json={"title": "Forbidden link", "contact_id": contact.json()["id"]}).status_code == 404
    assert client.get(f"/api/v1/crm/leads/{lead.json()['id']}/activities", headers=other).status_code == 404


def test_import_preview_csv_xlsx_and_duplicates(client: TestClient):
    headers = account(client, "import@example.com", "Imports")
    csv_bytes = b"name,email,phone\nJane,JANE@example.com,123\nDuplicate,jane@example.com,456\nBad,not-an-email,0\n"
    preview = client.post("/api/v1/crm/imports/preview", headers=headers, files={"file": ("contacts.csv", csv_bytes, "text/csv")})
    assert preview.status_code == 200, preview.text
    assert [row["status"] for row in preview.json()["rows"]] == ["ready", "duplicate", "invalid"]
    valid = [row["data"] for row in preview.json()["rows"] if row["status"] == "ready"]
    result = client.post("/api/v1/crm/imports/contacts", headers=headers, json={"contacts": valid})
    assert result.status_code == 201 and result.json() == {"created": 1, "skipped": 0}
    assert client.post("/api/v1/crm/imports/contacts", headers=headers, json={"contacts": valid}).json()["skipped"] == 1
    workbook = Workbook()
    workbook.active.append(["name", "email"])
    workbook.active.append(["Jane", "jane@example.com"])
    output = io.BytesIO()
    workbook.save(output)
    xlsx = client.post("/api/v1/crm/imports/preview", headers=headers, files={"file": ("contacts.xlsx", output.getvalue())})
    assert xlsx.status_code == 200, xlsx.text
    assert xlsx.json()["rows"][0]["status"] == "duplicate"


def test_employee_can_read_but_cannot_change_crm(client: TestClient):
    headers = account(client, "crm-admin@example.com", "Team")
    with patch("app.api.routes.organizations.send_invitation_email", new=AsyncMock()) as send:
        invitation = client.post("/api/v1/organizations/current/invitations", headers=headers,
                                 json={"email": "crm-worker@example.com", "role": "employee"})
    assert invitation.status_code == 201
    token = send.await_args.args[2]
    register_and_verify(client, "crm-worker@example.com", "Worker personal")
    worker = login(client, "crm-worker@example.com")
    accepted = client.post("/api/v1/organizations/invitations/accept", headers={"X-CSRF-Token": worker["csrf_token"]}, json={"token": token})
    assert accepted.status_code == 200
    worker_headers = {"X-Organization-ID": headers["X-Organization-ID"], "X-CSRF-Token": worker["csrf_token"]}
    assert client.get("/api/v1/crm/leads", headers=worker_headers).status_code == 200
    assert client.post("/api/v1/crm/leads", headers=worker_headers, json={"title": "Forbidden"}).status_code == 403
    assert client.post("/api/v1/crm/imports/preview", headers=worker_headers, files={"file": ("a.csv", b"name,email\nA,a@example.com")}).status_code == 403
