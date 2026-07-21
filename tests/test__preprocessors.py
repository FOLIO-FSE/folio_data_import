import pytest
import pymarc
from folio_data_import.marc_preprocessors._preprocessors import (
    _get_record_id,
    MARCPreprocessor,
    clean_non_ff_999_fields,
    fix_bib_leader,
    prepend_prefix_001,
    prepend_ppn_prefix_001,
    prepend_abes_prefix_001,
    strip_999_ff_fields,
    sudoc_supercede_prep,
    clean_empty_fields,
    clean_999_fields,
)


def test_prepend_ppn_prefix_001():
    processor = MARCPreprocessor("prepend_ppn_prefix_001")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record = processor.do_work(record)
    assert record['001'].data == '(PPN)123456'


def test_prepend_abes_prefix_001():
    processor = MARCPreprocessor("prepend_abes_prefix_001")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record = processor.do_work(record)
    assert record['001'].data == '(ABES)123456'


def test_prepend_prefix_001():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record = prepend_prefix_001(record, 'TEST')
    assert record['001'].data == '(TEST)123456'


def test_strip_999_ff_fields():
    processor = MARCPreprocessor("strip_999_ff_fields")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='999', indicators=['f', 'f']))
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' ']))
    record = processor.do_work(record)
    assert len(record.get_fields('999')) == 1


def test_sudoc_supercede_prep():
    processor = MARCPreprocessor("sudoc_supercede_prep")
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
    record = processor.do_work(record)
    assert record.get_fields('935')[0]["a"] == '(ABES)234567'
    assert record.get_fields('935')[1]["a"] == '(ABES)345678'
    assert record['001'].data == '(ABES)123456'


def test_clean_empty_fields():
    processor = MARCPreprocessor("clean_empty_fields")
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
    record = processor.do_work(record)
    assert len(record.get_fields('010')) == 0
    assert len(record.get_fields('035')) == 1
    assert len(record.get_fields('650')) == 1
    assert len(record.get_fields('180')) == 1
    assert len(record.get_fields('245')) == 1
    assert len(record.get_fields('020')) == 1
    with pytest.raises(KeyError):
        record['020']['a']
    assert record["020"].get("y", "") == "0123-4567"

def test_fix_bib_leader():
    preprocessor = MARCPreprocessor("fix_bib_leader")
    record = pymarc.Record()
    record.leader = pymarc.Leader('01234mbm a2200349 a 4500')
    fields=[
        pymarc.Field(tag='001', data='123456'),
        pymarc.Field(tag='035', indicators=[' ', ' '], subfields=[
            pymarc.field.Subfield('a', 'ocn123456789')
        ]),
        pymarc.Field(tag='245', indicators=pymarc.Indicators(*[' ', ' ']), subfields=[
            pymarc.field.Subfield('a', 'Test: '),
            pymarc.field.Subfield('b', 'a test / '),
            pymarc.field.Subfield('c', 'by Test')
        ])
    ]
    for field in fields:
        record.add_field(field)
    record = preprocessor.do_work(record)
    assert record.leader[5] == 'c'
    assert record.leader[6] == 'a'


def test_clean_999_fields():
    preprocessor = MARCPreprocessor("clean_999_fields")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record.add_field(pymarc.Field(tag='999', indicators=['f', 'f'], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    record = preprocessor.do_work(record)
    assert len(record.get_fields('999')) == 0
    assert len(record.get_fields('945')) == 1
    assert record['945'].indicators == pymarc.Indicators(*[' ', ' '])


def test_clean_non_ff_999_fields():
    preprocessor = MARCPreprocessor("clean_non_ff_999_fields")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record.add_field(pymarc.Field(tag='999', indicators=['f', 'f'], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    record = preprocessor.do_work(record)
    assert len(record.get_fields('999')) == 1
    assert len(record.get_fields('945')) == 1


def test__get_preprocessor_functions():
    preprocessor_class = MARCPreprocessor("clean_999_fields,clean_empty_fields")
    assert preprocessor_class.preprocessors[0][0].__name__ == "clean_999_fields"
    assert preprocessor_class.preprocessors[1][0].__name__ == "clean_empty_fields"


def test_get_record_id_default_001():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    assert _get_record_id(record) == '123456'


def test_get_record_id_custom_control_field():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='003', data='OCoLC'))
    assert _get_record_id(record, record_id_field='003') == 'OCoLC'


def test_get_record_id_custom_field_with_subfield():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='907', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '.b123456789')
    ]))
    assert _get_record_id(record, record_id_field='907', record_id_subfield='a') == '.b123456789'


def test_get_record_id_field_absent_returns_unknown():
    record = pymarc.Record()
    assert _get_record_id(record) == 'UNKNOWN'


def test_get_record_id_subfield_absent_returns_unknown():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='907', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('b', 'something')
    ]))
    assert _get_record_id(record, record_id_field='907', record_id_subfield='a') == 'UNKNOWN'


def test_get_record_id_empty_field_value_returns_unknown():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data=''))
    assert _get_record_id(record) == 'UNKNOWN'


def test_get_record_id_extra_kwargs_ignored():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    assert _get_record_id(record, some_other_kwarg='foo') == '123456'


# --- preprocessors using record_id_field / record_id_subfield ---

def test_clean_non_ff_999_fields_custom_record_id(caplog):
    """Preprocessor logs the 907$a value as identifier when 001 is absent."""
    preprocessor = MARCPreprocessor(
        "clean_non_ff_999_fields",
        default={"record_id_field": "907", "record_id_subfield": "a"},
    )
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='907', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '.b987654321')
    ]))
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    with caplog.at_level(26):
        record = preprocessor.do_work(record)
    assert '.b987654321' in caplog.text
    assert len(record.get_fields('945')) == 1


def test_fix_bib_leader_custom_record_id(caplog):
    """Preprocessor logs the 907$a value as identifier when 001 is absent."""
    preprocessor = MARCPreprocessor(
        "fix_bib_leader",
        default={"record_id_field": "907", "record_id_subfield": "a"},
    )
    record = pymarc.Record()
    record.leader = pymarc.Leader('01234mbm a2200349 a 4500')
    record.add_field(pymarc.Field(tag='907', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '.b111222333')
    ]))
    with caplog.at_level(26):
        record = preprocessor.do_work(record)
    assert '.b111222333' in caplog.text
    assert record.leader[5] == 'c'
    assert record.leader[6] == 'a'


def test_preprocessor_logs_unknown_when_id_field_absent(caplog):
    """Falls back to UNKNOWN when neither 001 nor the configured field is present."""
    preprocessor = MARCPreprocessor("clean_non_ff_999_fields")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    with caplog.at_level(26):
        record = preprocessor.do_work(record)
    assert 'UNKNOWN' in caplog.text
