from unittest.mock import Mock
from folio_data_import.MARCDataImport import MARCImportJob
from folioclient import FolioClient
import pytest


@pytest.fixture
def folio_client():
    folio_client = Mock(spec=FolioClient)
    return folio_client


@pytest.fixture
def marc_import_job(folio_client):
    marc_import_job = Mock(spec=MARCImportJob)
    return marc_import_job
