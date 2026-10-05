import io

import docx
import pytest
import yaml

from core.pipeline import analyse, analyse_file

KINDS = {"clause", "missing", "risk", "compliance", "obligation"}


def _expected(samples_dir):
    with (samples_dir / "expected.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.mark.parametrize(
    "sample",
    [
        "employment_agreement.txt",
        "supply_agreement.txt",
        "lease_agreement.txt",
        "nda.txt",
        "partnership_agreement.txt",
        "service_level_agreement.txt",
        "loan_agreement.txt",
    ],
)
def test_analyse_samples(samples_dir, sample):
    text = (samples_dir / sample).read_text(encoding="utf-8")
    result = analyse(text)

    assert result["contract_type"] == _expected(samples_dir)[sample]["contract_type"]

    fids = [f["fid"] for f in result["findings"]]
    assert len(fids) == len(set(fids))

    for finding in result["findings"]:
        assert finding["kind"] in KINDS
        if finding["char_start"] is not None:
            assert (
                text[finding["char_start"] : finding["char_end"]]
                == finding["excerpt"]
            )


def test_analyse_file_docx(samples_dir):
    text = (samples_dir / "employment_agreement.txt").read_text(encoding="utf-8")
    document = docx.Document()
    for paragraph in text.split("\n"):
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)

    result = analyse_file(buffer.getvalue(), "employment.docx")
    assert len(result["clauses"]) > 1
    assert result["contract_type"] == "employment"


def test_analyse_rejects_empty_text():
    with pytest.raises(ValueError, match="little or no readable text"):
        analyse("")


def test_analyse_rejects_near_empty_text():
    # A scanned PDF often yields only a few stray characters.
    with pytest.raises(ValueError, match="needs OCR first"):
        analyse("Page 1\n\n  scanned  \n" * 5)


def test_unsplittable_text_sets_warning_and_skips_missing():
    # 300 words, no headings: one clause, so "missing" findings would be false.
    sentence = "The parties agree to work together in good faith on this project. "
    text = sentence * 25  # 12 words x 25 = 300 words
    assert len(text.split()) == 300
    result = analyse(text)
    assert result["summary"]["segmentation_warning"] is True
    assert not [f for f in result["findings"] if f["kind"] == "missing"]


TITLE_CASE_CONTRACT = """Supply Agreement

This Supply Agreement is made between Acme Foods Limited (the Supplier) and Delta Stores Plc (the Buyer) for the supply of packaged rice.

Supply of Products

The Supplier shall deliver the products listed in each purchase order to the Buyer's warehouse in Lagos within 14 days.

Payment

The Buyer shall pay each invoice within 30 days of receipt by bank transfer to the account named by the Supplier.

Termination

Either party may terminate this Agreement by giving 30 days written notice to the other party. Either party may terminate this Agreement immediately if the other party commits a material breach.

Governing Law

This Agreement shall be governed by and construed in accordance with the laws of the Federal Republic of Nigeria.

Dispute Resolution

Any dispute arising out of or in connection with this Agreement shall be referred to arbitration in Lagos under the Arbitration and Mediation Act 2023.
"""


def test_title_case_contract_is_segmented_and_labelled():
    result = analyse(TITLE_CASE_CONTRACT)
    assert result["summary"]["segmentation_warning"] is False
    labels = set(result["labels"])
    for label in ("governing_law", "dispute_resolution", "termination"):
        assert label in labels
    high_missing = {
        f["label"]
        for f in result["findings"]
        if f["kind"] == "missing" and f["severity"] == "High"
    }
    assert not high_missing & {"governing_law", "dispute_resolution", "termination"}


def test_samples_have_no_segmentation_warning(samples_dir):
    text = (samples_dir / "nda.txt").read_text(encoding="utf-8")
    assert analyse(text)["summary"]["segmentation_warning"] is False
