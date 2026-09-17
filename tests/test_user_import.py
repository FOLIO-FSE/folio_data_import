import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from folioclient import FolioClient

from folio_data_import import DATA_ISSUE_LVL_NUM
from folio_data_import.UserImport import UserImporter


@pytest.fixture
def folio_client():
    folio_client = Mock(spec=FolioClient)
    folio_client.module_versions = []
    return folio_client


def make_importer(folio_client, default_preferred_contact_type="002"):
    folio_client.folio_get_all.return_value = []
    config = UserImporter.Config(
        library_name="Test Library",
        default_preferred_contact_type=default_preferred_contact_type,
    )
    return UserImporter(folio_client, config)


def test_build_ref_data_id_map(folio_client):
    # Mock the response from folio_get_all method
    def mock_folio_get_all(endpoint, key):
        if endpoint == "/groups":
            return [
                {"id": "1", "group": "Group1"},
                {"id": "2", "group": "Group2"},
                {"id": "3", "group": "Group3"},
            ]
        if endpoint == "/addresstypes":
            return [
                {"id": "10", "addressType": "Type1"},
                {"id": "20", "addressType": "Type2"},
                {"id": "30", "addressType": "Type3"},
            ]
        if endpoint == "/departments":
            return [
                {"id": "100", "name": "Department1"},
                {"id": "200", "name": "Department2"},
                {"id": "300", "name": "Department3"},
            ]

        if endpoint == "/service-points":
            return [
                {"id": "100", "name": "ServicePoint1"},
                {"id": "200", "name": "ServicePoint2"},
                {"id": "300", "name": "ServicePoint3"},
            ]

    folio_client.folio_get_all = mock_folio_get_all

    # Test the build_ref_data_id_map method
    patron_group_map = UserImporter.build_ref_data_id_map(
        folio_client, "/groups", "usergroups", "group"
    )
    assert patron_group_map == {"Group1": "1", "Group2": "2", "Group3": "3"}

    address_type_map = UserImporter.build_ref_data_id_map(
        folio_client, "/addresstypes", "addressTypes", "addressType"
    )
    assert address_type_map == {"Type1": "10", "Type2": "20", "Type3": "30"}

    department_map = UserImporter.build_ref_data_id_map(
        folio_client, "/departments", "departments", "name"
    )
    assert department_map == {
        "Department1": "100",
        "Department2": "200",
        "Department3": "300",
    }

    service_point_map = UserImporter.build_ref_data_id_map(
        folio_client, "/service-points", "servicepoints", "name"
    )
    assert service_point_map == {
        "ServicePoint1": "100",
        "ServicePoint2": "200",
        "ServicePoint3": "300",
    }


def test_normalize_preferred_contact_type_from_name(folio_client):
    importer = make_importer(folio_client)
    assert importer.normalize_preferred_contact_type("email") == "002"


def test_normalize_preferred_contact_type_uses_numeric_default_when_invalid_input(folio_client):
    importer = make_importer(folio_client, default_preferred_contact_type="005")
    assert importer.normalize_preferred_contact_type("not-a-real-value") == "005"


def test_normalize_preferred_contact_type_uses_named_default_when_invalid_input(folio_client):
    importer = make_importer(folio_client, default_preferred_contact_type="phone")
    assert importer.normalize_preferred_contact_type("not-a-real-value") == "004"


def test_create_new_user_normalizes_preferred_contact_type(folio_client):
    importer = make_importer(folio_client)
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"id": "new-user-id"}
    importer.http_client = Mock()
    importer.http_client.post = AsyncMock(return_value=response)
    importer.folio_client.okapi_headers = {"x-okapi-token": "test"}

    user_obj = {"personal": {"preferredContactTypeId": "email"}}

    created_user = asyncio.run(importer.create_new_user(user_obj))

    assert user_obj["personal"]["preferredContactTypeId"] == "002"
    assert created_user == {"id": "new-user-id"}


def test_map_departments_logs_data_issue_for_unmapped_department(folio_client, caplog):
    importer = make_importer(folio_client)
    importer.department_map = {"Department1": "100"}
    user_obj = {"username": "jdoe", "departments": ["Department1", "UnknownDept"]}

    with caplog.at_level(DATA_ISSUE_LVL_NUM, logger="folio_data_import.UserImport"):
        importer.map_departments(user_obj, line_number=9)

    assert user_obj["departments"] == ["100"]
    data_issue_messages = [
        record.message for record in caplog.records if record.levelno == DATA_ISSUE_LVL_NUM
    ]
    assert data_issue_messages
    assert data_issue_messages[0].startswith("DATA ISSUE\t10:username=jdoe\tDepartment removed:")


def make_custom_fields_response(custom_fields):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {
        "customFields": custom_fields,
        "totalRecords": len(custom_fields),
    }
    return response


SINGLE_SELECT_FIELD = {
    "refId": "department_1",
    "type": "SINGLE_SELECT_DROPDOWN",
    "selectField": {
        "multiSelect": False,
        "options": {
            "values": [
                {"id": "opt_0", "value": "Faculty"},
                {"id": "opt_1", "value": "Staff"},
            ]
        },
    },
}

MULTI_SELECT_FIELD = {
    "refId": "interests_1",
    "type": "MULTI_SELECT_DROPDOWN",
    "selectField": {
        "multiSelect": True,
        "options": {
            "values": [
                {"id": "opt_0", "value": "Music"},
                {"id": "opt_1", "value": "Art"},
            ]
        },
    },
}


def test_build_custom_field_option_maps_resolves_select_fields(folio_client):
    folio_client.module_versions = ["mod-users-19.4.0", "mod-other-1.0.0"]
    folio_client.httpx_client = Mock()
    folio_client.httpx_client.get.return_value = make_custom_fields_response(
        [SINGLE_SELECT_FIELD, MULTI_SELECT_FIELD]
    )

    option_maps = UserImporter.build_custom_field_option_maps(folio_client)

    assert option_maps == {
        "department_1": {
            "multi": False,
            "valid_ids": {"opt_0", "opt_1"},
            "labels": {"Faculty": "opt_0", "Staff": "opt_1"},
        },
        "interests_1": {
            "multi": True,
            "valid_ids": {"opt_0", "opt_1"},
            "labels": {"Music": "opt_0", "Art": "opt_1"},
        },
    }
    _, kwargs = folio_client.httpx_client.get.call_args
    assert kwargs["headers"] == {"x-okapi-module-id": "mod-users-19.4.0"}


def test_build_custom_field_option_maps_returns_empty_without_module_id(folio_client):
    folio_client.module_versions = ["mod-other-1.0.0"]

    option_maps = UserImporter.build_custom_field_option_maps(folio_client)

    assert option_maps == {}


def test_map_custom_fields_resolves_label_to_option_id(folio_client):
    importer = make_importer(folio_client)
    importer.custom_field_option_maps = {
        "department_1": {
            "multi": False,
            "valid_ids": {"opt_0", "opt_1"},
            "labels": {"Faculty": "opt_0", "Staff": "opt_1"},
        }
    }
    user_obj = {"customFields": {"department_1": "Faculty"}}

    importer.map_custom_fields(user_obj, line_number=1)

    assert user_obj["customFields"]["department_1"] == "opt_0"


def test_map_custom_fields_passes_through_existing_option_id(folio_client):
    importer = make_importer(folio_client)
    importer.custom_field_option_maps = {
        "department_1": {
            "multi": False,
            "valid_ids": {"opt_0", "opt_1"},
            "labels": {"Faculty": "opt_0", "Staff": "opt_1"},
        }
    }
    user_obj = {"customFields": {"department_1": "opt_1"}}

    importer.map_custom_fields(user_obj, line_number=1)

    assert user_obj["customFields"]["department_1"] == "opt_1"


def test_map_custom_fields_case_insensitive_fallback_match(folio_client):
    importer = make_importer(folio_client)
    importer.custom_field_option_maps = {
        "department_1": {
            "multi": False,
            "valid_ids": {"opt_0", "opt_1"},
            "labels": {"Faculty": "opt_0", "Staff": "opt_1"},
        }
    }
    user_obj = {"customFields": {"department_1": " faculty "}}

    importer.map_custom_fields(user_obj, line_number=1)

    assert user_obj["customFields"]["department_1"] == "opt_0"


def test_map_custom_fields_resolves_multi_select_list(folio_client):
    importer = make_importer(folio_client)
    importer.custom_field_option_maps = {
        "interests_1": {
            "multi": True,
            "valid_ids": {"opt_0", "opt_1"},
            "labels": {"Music": "opt_0", "Art": "opt_1"},
        }
    }
    user_obj = {"customFields": {"interests_1": ["Music", "opt_1"]}}

    importer.map_custom_fields(user_obj, line_number=1)

    assert user_obj["customFields"]["interests_1"] == ["opt_0", "opt_1"]


def test_map_custom_fields_logs_data_issue_for_unmapped_value(folio_client, caplog):
    importer = make_importer(folio_client)
    importer.custom_field_option_maps = {
        "department_1": {
            "multi": False,
            "valid_ids": {"opt_0", "opt_1"},
            "labels": {"Faculty": "opt_0", "Staff": "opt_1"},
        }
    }
    user_obj = {"username": "jdoe", "customFields": {"department_1": "Not A Real Department"}}

    with caplog.at_level(DATA_ISSUE_LVL_NUM, logger="folio_data_import.UserImport"):
        importer.map_custom_fields(user_obj, line_number=9)

    assert "department_1" not in user_obj["customFields"]
    data_issue_messages = [
        record.message for record in caplog.records if record.levelno == DATA_ISSUE_LVL_NUM
    ]
    assert data_issue_messages
    assert data_issue_messages[0].startswith(
        "DATA ISSUE\t10:username=jdoe\tCustom field value removed:"
    )


def test_build_record_failed_message_for_unique_conflict(folio_client):
    importer = make_importer(folio_client)
    user_obj = {
        "username": "jdoe",
        "barcode": "123456",
        "externalSystemId": "abc-123",
        "personal": {"email": "jdoe@example.org"},
    }
    payload = {
        "errors": [
            {
                "message": "duplicate key value violates unique constraint",
                "parameters": [
                    {"key": "username", "value": "jdoe"},
                    {"key": "barcode", "value": "123456"},
                ],
            }
        ]
    }

    message = importer._build_record_failed_message(
        "create",
        user_obj,
        payload,
        "duplicate key value violates unique constraint",
        422,
    )

    assert "User create failed." in message
    assert "Unique field conflict in /users." in message
    assert 'username="jdoe"' in message
    assert 'barcode="123456"' in message
