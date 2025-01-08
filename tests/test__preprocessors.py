from unittest.mock import Mock
from folioclient import FolioClient
import pytest
import pymarc
from folio_data_import.marc_preprocessors._preprocessors import *


def test_prepend_ppn_prefix_001():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record = prepend_ppn_prefix_001(record)
    assert record['001'].data == '(PPN)123456'

def test_prepend_abes_prefix_001():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record = prepend_abes_prefix_001(record)
    assert record['001'].data == '(ABES)123456'

def test_prepend_prefix_001():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record = prepend_prefix_001(record, 'TEST')
    assert record['001'].data == '(TEST)123456'

def test_strip_999_ff_fields():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='999', indicators=['f', 'f']))
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' ']))
    record = strip_999_ff_fields(record)
    assert len(record.get_fields('999')) == 1

def test_sudoc_supercede_prep():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record.add_field(pymarc.Field(tag='035', indicators=['', ''], subfields=[
        pymarc.field.Subfield('a', '234567'),
        pymarc.field.Subfield('9', 'sudoc')
    ]))
    record.add_field(pymarc.Field(tag='035', indicators=['', ''], subfields=[
        pymarc.field.Subfield('a', '345678'),
        pymarc.field.Subfield('9', 'sudoc')
    ]))
    record = sudoc_supercede_prep(record)
    assert record.get_fields('935')[0]["a"] == '(ABES)234567'
    assert record.get_fields('935')[1]["a"] == '(ABES)345678'
    assert record['001'].data == '(ABES)123456'
