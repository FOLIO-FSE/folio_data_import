from multiprocessing import Value
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


def test_clean_empty_fields():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    bad_010 = pymarc.Field(tag='010', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '')
    ])
    record.add_field(bad_010)
    bad_020 = pymarc.Field(tag='020', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', ''),
        pymarc.field.Subfield('y', '0123-4567'),
    ])
    record.add_field(bad_020)
    empty_020 = pymarc.Field(tag='020', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', ''),
        pymarc.field.Subfield('y', ''),
    ])
    record.add_field(empty_020)
    good_035 = pymarc.Field(tag='035', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', 'ocn123456789')
    ])
    record.add_field(good_035)
    bad_035 = pymarc.Field(tag='035', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '')
    ])
    record.add_field(bad_035)
    bad_650 = pymarc.Field(tag='650', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '')
    ])
    record.add_field(bad_650)
    good_650 = pymarc.Field(tag='650', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', 'Test')
    ])
    record.add_field(good_650)
    bad_180 = pymarc.Field(tag='180', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('x', '')
    ])
    record.add_field(bad_180)
    good_180 = pymarc.Field(tag='180', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('x', 'Test')
    ])
    record.add_field(good_180)
    good_245 = pymarc.Field(tag='245', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', 'Test: '),
        pymarc.field.Subfield('b', 'a test / '),
        pymarc.field.Subfield('c', 'by Test')
    ])
    record.add_field(good_245)
    record = clean_empty_fields(record)
    assert len(record.get_fields('010')) == 0
    assert len(record.get_fields('035')) == 1
    assert len(record.get_fields('650')) == 1
    assert len(record.get_fields('180')) == 1
    assert len(record.get_fields('245')) == 1
    assert len(record.get_fields('020')) == 1
    with pytest.raises(KeyError):
        record['020']['a']
    assert record["020"].get("y", "") == "0123-4567"

