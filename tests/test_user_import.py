from unittest.mock import Mock

import pytest
from folioclient import FolioClient

from folio_data_import.UserImport import UserImporter


@pytest.fixture
def folio_client():
    folio_client = Mock(spec=FolioClient)
    return folio_client


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
