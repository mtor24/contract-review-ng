from itertools import groupby

import pytest

from core.ingest import clean_text
from core.segment import segment

TITLE_BY_FILE = {
    "employment_agreement.txt": "EMPLOYMENT AGREEMENT",
    "lease_agreement.txt": "LEASE AGREEMENT",
    "loan_agreement.txt": "LOAN AGREEMENT",
    "nda.txt": "NON-DISCLOSURE AGREEMENT",
    "partnership_agreement.txt": "PARTNERSHIP AGREEMENT",
    "service_level_agreement.txt": "SERVICE LEVEL AGREEMENT",
    "supply_agreement.txt": "SUPPLY AGREEMENT",
}

NUMBERED_TEXT = (
    "Preamble words here.\n"
    "\n"
    "1. DEFINITIONS\n"
    "\n"
    "1.1 In this Agreement the following words apply.\n"
    "\n"
    "1.2 Headings are for convenience only.\n"
)


def test_numbered_clauses_levels_and_inherited_heading():
    clauses = segment(NUMBERED_TEXT)
    by_number = {c.number: c for c in clauses if c.number}
    assert by_number["1"].level == 1
    assert by_number["1.1"].level == 2
    assert by_number["1.2"].level == 2
    # Level 2 clauses inherit the nearest preceding level 1 heading.
    assert by_number["1.1"].heading == "DEFINITIONS"
    assert by_number["1.2"].heading == "DEFINITIONS"


def test_keyword_style_clause_heading():
    clauses = segment("Clause 3: TERMINATION\n\n3.1 Either party may terminate.\n")
    by_number = {c.number: c for c in clauses if c.number}
    assert by_number["3"].number == "3"
    assert by_number["3"].heading == "TERMINATION"


def test_all_caps_heading_style():
    text = (
        "Preamble words here.\n"
        "\n"
        "GOVERNING LAW\n"
        "\n"
        "This Agreement is governed by Nigerian law.\n"
    )
    clauses = segment(text)
    headings = [c for c in clauses if c.heading == "GOVERNING LAW"]
    assert len(headings) == 1
    assert headings[0].number is None
    assert headings[0].level == 1


def test_list_items_stay_inside_clause():
    text = (
        "2. OBLIGATIONS\n"
        "\n"
        "2.1 The Recipient agrees to:\n"
        "\n"
        "(a) keep information confidential;\n"
        "\n"
        "(b) use it only for the permitted purpose.\n"
    )
    clauses = segment(text)
    two_one = next(c for c in clauses if c.number == "2.1")
    assert "(a) keep information confidential;" in two_one.text
    assert "(b) use it only for the permitted purpose." in two_one.text
    # No clause may be created for a list item.
    assert all(not c.text.startswith("(") for c in clauses)


def test_preamble_becomes_seq_zero():
    clauses = segment(NUMBERED_TEXT)
    assert clauses[0].seq == 0
    assert clauses[0].heading == "PREAMBLE"
    assert clauses[0].level == 0
    assert clauses[0].number is None


SAMPLE_FILES = [
    "employment_agreement.txt",
    "lease_agreement.txt",
    "loan_agreement.txt",
    "nda.txt",
    "partnership_agreement.txt",
    "service_level_agreement.txt",
    "supply_agreement.txt",
]


@pytest.mark.parametrize("filename", SAMPLE_FILES)
def test_offsets_invariant_and_minimum_clause_count(samples_dir, filename):
    text = (samples_dir / filename).read_text(encoding="utf-8")
    clauses = segment(text)
    assert len(clauses) >= 8
    for c in clauses:
        assert text[c.char_start : c.char_end] == c.text


def test_lease_single_word_caps_headings(samples_dir):
    text = clean_text((samples_dir / "lease_agreement.txt").read_text(encoding="utf-8"))
    clauses = segment(text)
    assert len(clauses) >= 14
    headings = {c.heading for c in clauses}
    for expected in ("PARTIES", "TERM", "RENT", "RENT REVIEW", "NOTICES", "GOVERNING LAW"):
        assert expected in headings


@pytest.mark.parametrize("filename", SAMPLE_FILES)
def test_title_stays_in_preamble_and_no_company_clauses(samples_dir, filename):
    text = clean_text((samples_dir / filename).read_text(encoding="utf-8"))
    clauses = segment(text)
    assert clauses[0].seq == 0
    assert clauses[0].heading == "PREAMBLE"
    assert TITLE_BY_FILE[filename] in clauses[0].text
    # Signature-block company names must never become clause headings.
    assert all(not (c.heading or "").endswith("LIMITED") for c in clauses)


def test_between_colon_is_not_a_clause_start():
    clauses = segment("BETWEEN:\n\n(1) Some party description.\n")
    assert all(c.heading != "BETWEEN:" for c in clauses)


# Frozen before the Title Case heading rule was added: (clause count, runs of
# (heading, how many consecutive clauses carry it)). Any change to segment.py
# that alters how the seven samples split must fail here, on purpose.
FROZEN_SEGMENTATION = {
    "employment_agreement.txt": (
        38,
        [
            ('PREAMBLE', 1),
            ('APPOINTMENT AND COMMENCEMENT', 4),
            ('DUTIES AND RESPONSIBILITIES', 5),
            ('SALARY AND BENEFITS', 5),
            ('CONFIDENTIALITY', 4),
            ('NON-COMPETE', 4),
            ('TERMINATION', 5),
            ('PERSONAL DATA', 3),
            ('GENERAL', 5),
            ('GOVERNING LAW', 2),
        ],
    ),
    "lease_agreement.txt": (
        14,
        [
            ('PREAMBLE', 1),
            ('PARTIES', 1),
            ('DEMISE', 1),
            ('TERM', 1),
            ('RENT', 1),
            ('RENT REVIEW', 1),
            ("TENANT'S COVENANTS", 1),
            ("LANDLORD'S COVENANTS", 1),
            ('REPAIRS', 1),
            ('HOLDING OVER', 1),
            ('TERMINATION', 1),
            ('NOTICES', 1),
            ('GOVERNING LAW', 1),
            ('DISPUTE RESOLUTION', 1),
        ],
    ),
    "loan_agreement.txt": (
        48,
        [
            ('PREAMBLE', 1),
            ('THE FACILITY', 4),
            ('INTEREST', 3),
            ('REPAYMENT', 5),
            ('DEFAULT INTEREST', 3),
            ('SECURITY', 5),
            ('REPRESENTATIONS AND WARRANTIES', 5),
            ('COVENANTS', 5),
            ('EVENTS OF DEFAULT', 6),
            ('ACCELERATION AND TERMINATION', 4),
            ('GENERAL', 4),
            ('GOVERNING LAW AND JURISDICTION', 3),
        ],
    ),
    "nda.txt": (
        29,
        [
            ('PREAMBLE', 1),
            ('DEFINITION OF CONFIDENTIAL INFORMATION', 2),
            ('OBLIGATIONS OF THE RECIPIENT', 4),
            ('EXCLUSIONS', 2),
            ('RETURN OF INFORMATION', 3),
            ('TERM', 3),
            ('REMEDIES', 3),
            ('TERMINATION', 4),
            ('GENERAL', 4),
            ('GOVERNING LAW AND JURISDICTION', 3),
        ],
    ),
    "partnership_agreement.txt": (
        49,
        [
            ('PREAMBLE', 1),
            ('FORMATION AND NAME', 4),
            ('NATURE OF BUSINESS', 3),
            ('CAPITAL CONTRIBUTIONS', 7),
            ('PROFIT SHARING', 6),
            ('MANAGEMENT', 6),
            ('BANKING AND ACCOUNTS', 3),
            ('ADMISSION OF NEW PARTNERS', 3),
            ('RETIREMENT AND EXPULSION', 4),
            ('DISSOLUTION AND TERMINATION', 5),
            ('RESTRAINT AFTER CEASING TO BE A PARTNER', 2),
            ('GOVERNING LAW', 2),
            ('DISPUTE RESOLUTION', 3),
        ],
    ),
    "service_level_agreement.txt": (
        56,
        [
            ('PREAMBLE', 1),
            ('SERVICES', 5),
            ('SERVICE LEVELS', 8),
            ('SERVICE CREDITS', 5),
            ('FEES AND PAYMENT', 4),
            ('DATA PROTECTION', 5),
            ('CONFIDENTIALITY', 3),
            ('LIMITATION OF LIABILITY', 3),
            ('INDEMNITIES', 4),
            ('FORCE MAJEURE', 3),
            ('TERM AND TERMINATION', 5),
            ('NOTICES', 3),
            ('ASSIGNMENT', 2),
            ('GOVERNING LAW', 2),
            ('DISPUTE RESOLUTION', 3),
        ],
    ),
    "supply_agreement.txt": (
        40,
        [
            ('PREAMBLE', 1),
            ('DEFINITIONS', 4),
            ('SUPPLY OF PRODUCTS', 5),
            ('PRICE AND PAYMENT', 5),
            ('LIABILITY', 4),
            ('INDEMNITY', 3),
            ('TERM AND RENEWAL', 4),
            ('FORCE MAJEURE', 4),
            ('GOVERNING LAW', 2),
            ('DISPUTE RESOLUTION', 4),
            ('GENERAL', 4),
        ],
    ),
}


@pytest.mark.parametrize("filename", SAMPLE_FILES)
def test_sample_segmentation_is_frozen(samples_dir, filename):
    text = clean_text((samples_dir / filename).read_text(encoding="utf-8"))
    clauses = segment(text)
    runs = [(h, len(list(g))) for h, g in groupby(c.heading for c in clauses)]
    count, expected_runs = FROZEN_SEGMENTATION[filename]
    assert len(clauses) == count
    assert runs == expected_runs


TITLE_CASE_TEXT = (
    "Supply Agreement\n"
    "\n"
    "This Agreement is made between Acme Foods Limited and Delta Stores Plc.\n"
    "\n"
    "Payment\n"
    "\n"
    "The Buyer shall pay each invoice within 30 days of receipt.\n"
    "\n"
    "Termination\n"
    "Either party may terminate this Agreement on 30 days written notice.\n"
    "\n"
    "Limitation of Liability\n"
    "\n"
    "Neither party is liable for indirect loss.\n"
    "\n"
    "Governing Law\n"
    "\n"
    "This Agreement is governed by the laws of the Federal Republic of Nigeria.\n"
    "\n"
    "Signed for and on behalf of\n"
    "Acme Foods Limited\n"
    "\n"
    "Name: Ada Obi\n"
    "Signature: ____________\n"
    "\n"
    "Delta Stores Plc\n"
    "\n"
    "Witness\n"
)


def test_title_case_headings_start_clauses():
    clauses = segment(TITLE_CASE_TEXT)
    headings = [c.heading for c in clauses]
    assert headings == [
        "PREAMBLE",
        "Payment",
        "Termination",
        "Limitation of Liability",
        "Governing Law",
    ]
    # The title is a heading-shaped first line but belongs to the preamble.
    assert "Supply Agreement" in clauses[0].text
    for c in clauses:
        assert TITLE_CASE_TEXT[c.char_start : c.char_end] == c.text


def test_title_case_signature_lines_stay_in_last_clause():
    last = segment(TITLE_CASE_TEXT)[-1]
    assert last.heading == "Governing Law"
    for line in ("Acme Foods Limited", "Name: Ada Obi", "Delta Stores Plc", "Witness"):
        assert line in last.text


def test_title_case_rule_needs_blank_line_before_and_body_after():
    # Sentence-like lines, lines glued to the previous paragraph and a heading
    # with nothing after it are not clause starts.
    text = (
        "Preamble words here.\n"
        "\n"
        "The Buyer Pays\n"
        "\n"
        "Some body text follows here.\n"
        "Governing Law\n"
        "This line follows a non-blank line.\n"
        "\n"
        "Notices:\n"
        "Body after a colon heading.\n"
        "\n"
        "the payment terms\n"
        "Lower case first word.\n"
        "\n"
        "Final Heading\n"
    )
    headings = [c.heading for c in segment(text)]
    assert headings == ["PREAMBLE", "The Buyer Pays"]


def test_title_case_rule_rejects_long_lines_and_lowercase_words():
    text = (
        "Title Line\n"
        "\n"
        "One Two Three Four Five Six Seven\n"
        "Body text here.\n"
        "\n"
        "Payment terms\n"
        "Body text here.\n"
    )
    assert [c.heading for c in segment(text)] == ["PREAMBLE"]
