"""
Integration test for UserImport's custom-field label resolution against a
real, live FOLIO environment (e.g. a FOLIO snapshot/reference environment).

Unlike tests/test_user_import.py, these tests make real HTTP requests and are
not run by default. They are gated behind the `integration` pytest marker and
are skipped automatically unless FOLIO_GATEWAY_URL, FOLIO_TENANT_ID,
FOLIO_USERNAME, and FOLIO_PASSWORD are set, e.g.:

    export FOLIO_GATEWAY_URL="https://folio-snapshot-okapi.dev.folio.org"
    export FOLIO_TENANT_ID="diku"
    export FOLIO_USERNAME="diku_admin"
    export FOLIO_PASSWORD="admin"
    uv run pytest tests/test_user_import_integration.py -m integration -v

These tests exist to guard against a regression where UserImporter's custom
field fetch used FolioClient's httpx_client directly, without the self-healing
"create a temporary client session if none is open" behavior that
folio_get_all gets for free. In production, that bug surfaced as:
"Error: Cannot send a request, as the client has been closed."
"""

import os
import uuid

import pytest
from folioclient import FolioClient

from folio_data_import.UserImport import UserImporter

FOLIO_GATEWAY_URL = os.environ.get("FOLIO_GATEWAY_URL")
FOLIO_TENANT_ID = os.environ.get("FOLIO_TENANT_ID")
FOLIO_USERNAME = os.environ.get("FOLIO_USERNAME")
FOLIO_PASSWORD = os.environ.get("FOLIO_PASSWORD")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all([FOLIO_GATEWAY_URL, FOLIO_TENANT_ID, FOLIO_USERNAME, FOLIO_PASSWORD]),
        reason=(
            "Set FOLIO_GATEWAY_URL, FOLIO_TENANT_ID, FOLIO_USERNAME, and FOLIO_PASSWORD "
            "to point at a live FOLIO environment to run this test."
        ),
    ),
]

CUSTOM_FIELD_NAME = "UserImport Integration Test Status"
ACTIVE_OPTION_LABEL = "Active"
OTHER_OPTION_LABEL = "Other"


def _find_users_module_id(folio_client: FolioClient) -> str:
    module_id = next(
        (m for m in folio_client.module_versions if m.startswith("mod-users-")), None
    )
    assert module_id, "Could not find a mod-users module on this tenant"
    return module_id


@pytest.fixture
def live_folio_client():
    # Deliberately NOT entered as a `with`/`async with` context manager here, to
    # mirror UserImport's own CLI entrypoint: FolioClient(...) and UserImporter(...)
    # are both constructed before the client is ever opened as a context manager.
    # Function-scoped (fresh per test) so that a test which fully closes its own
    # client (login/logout via `async with`) can't affect any other test.
    return FolioClient(FOLIO_GATEWAY_URL, FOLIO_TENANT_ID, FOLIO_USERNAME, FOLIO_PASSWORD)


@pytest.fixture(scope="module")
def admin_client():
    # A client used only to provision/clean up the shared custom field
    # definition, kept independent of whatever the tests do to their own
    # live_folio_client (e.g. fully logging out via `async with`, which tears
    # down folio_parameters and would otherwise break cleanup).
    return FolioClient(FOLIO_GATEWAY_URL, FOLIO_TENANT_ID, FOLIO_USERNAME, FOLIO_PASSWORD)


@pytest.fixture(scope="module")
def custom_field_definition(admin_client):
    module_id = _find_users_module_id(admin_client)
    headers = {"x-okapi-module-id": module_id}
    existing = next(
        (
            f
            for f in admin_client.folio_get_all("/custom-fields", "customFields", headers=headers)
            if f.get("name") == CUSTOM_FIELD_NAME
        ),
        None,
    )
    created_by_test = existing is None
    if created_by_test:
        # refId and order are server-generated (see folio-custom-fields'
        # CustomFieldsServiceImpl: setRefId/setOrder are always overwritten on
        # create), so they're deliberately omitted here rather than guessed.
        payload = {
            "name": CUSTOM_FIELD_NAME,
            "type": "SINGLE_SELECT_DROPDOWN",
            "entityType": "user",
            "visible": True,
            "required": False,
            "helpText": "Created by folio_data_import's UserImport integration test.",
            "selectField": {
                "multiSelect": False,
                "options": {
                    "values": [
                        {"value": ACTIVE_OPTION_LABEL, "default": True},
                        {"value": OTHER_OPTION_LABEL, "default": False},
                    ]
                },
            },
        }
        field = admin_client.folio_post("/custom-fields", payload, headers=headers)
    else:
        field = existing

    yield field

    if created_by_test:
        admin_client.folio_delete(f"/custom-fields/{field['id']}", headers=headers)


def test_user_importer_resolves_custom_field_label_against_live_folio(
    live_folio_client, custom_field_definition
):
    """
    Regression test: UserImporter.__init__ builds several reference-data maps
    via folio_client.folio_get_all (patron groups, address types, departments,
    service points) before building the custom-field option map. Each of those
    calls opens and closes its own temporary httpx client as a side effect. The
    custom-fields fetch used to bypass that self-healing behavior and would
    raise "Cannot send a request, as the client has been closed." here.
    """
    ref_id = custom_field_definition["refId"]
    option_ids_by_label = {
        value["value"]: value["id"]
        for value in custom_field_definition["selectField"]["options"]["values"]
    }

    config = UserImporter.Config(library_name="UserImport Integration Test")
    importer = UserImporter(live_folio_client, config)

    assert ref_id in importer.custom_field_option_maps
    assert importer.custom_field_option_maps[ref_id]["labels"] == option_ids_by_label

    user_obj = {"customFields": {ref_id: OTHER_OPTION_LABEL}}
    importer.map_custom_fields(user_obj, line_number=1)

    assert user_obj["customFields"][ref_id] == option_ids_by_label[OTHER_OPTION_LABEL]


@pytest.mark.asyncio
async def test_user_importer_creates_user_with_resolved_custom_field(
    live_folio_client, custom_field_definition
):
    """
    Fuller round-trip: resolves a human-readable custom field label to its
    FOLIO-assigned option id and POSTs a real user to /users with it, proving
    the fix avoids the downstream "Field status can only have following
    values" validation error from the original bug report. The created user
    is deleted afterward.
    """
    ref_id = custom_field_definition["refId"]
    option_ids_by_label = {
        value["value"]: value["id"]
        for value in custom_field_definition["selectField"]["options"]["values"]
    }

    config = UserImporter.Config(library_name="UserImport Integration Test")
    importer = UserImporter(live_folio_client, config)
    patron_group_id = next(iter(importer.patron_group_map.values()), None)
    assert patron_group_id, "Tenant has no patron groups to assign to the test user"

    user_obj = {
        "username": f"userimport_it_{uuid.uuid4().hex[:12]}",
        "active": True,
        "patronGroup": patron_group_id,
        "personal": {"lastName": "UserImport Integration Test User"},
        "customFields": {ref_id: OTHER_OPTION_LABEL},
    }
    importer.map_custom_fields(user_obj, line_number=1)
    assert user_obj["customFields"][ref_id] == option_ids_by_label[OTHER_OPTION_LABEL]

    created_user = None
    async with importer.folio_client:
        try:
            created_user = await importer.create_new_user(user_obj)
            assert (
                created_user["customFields"][ref_id]
                == option_ids_by_label[OTHER_OPTION_LABEL]
            )
        finally:
            if created_user:
                await importer.http_client.delete(
                    f"/users/{created_user['id']}",
                    headers=importer.folio_client.folio_headers,
                )
