"""Contract text shown through Streamlit Markdown must stay literal text."""

from ui.components import contract_options, md_escape


def test_md_escape_neutralises_images_links_and_latex():
    out = md_escape("![x](https://a.example/p.png) costs $5 and *bold* [link](https://b.example)")
    assert "![" not in out.replace("\!\[", "")
    assert "\$" in out and "$5" not in out.replace("\$5", "")
    assert "\*bold\*" in out
    assert "\[link\]" in out


def test_md_escape_handles_none_and_plain_text():
    assert md_escape(None) == ""
    assert md_escape("Supply Agreement") == "Supply Agreement"


def test_contract_options_keeps_same_titled_contracts_apart():
    contracts = [
        {"id": "a", "title": "Supply Agreement", "parties": [{"name": "Golden Root"}], "created_at": "2026-10-04"},
        {"id": "b", "title": "Supply Agreement", "parties": [{"name": "Golden Root"}], "created_at": "2026-10-04"},
    ]
    options = contract_options(contracts)
    assert set(options) == {"a", "b"}
    assert options["a"] != options["b"]
