"""Helpers for the Review page: upload form, summary tab, tab renderers.

Kept out of ui/pages/review.py so the page itself stays a readable flow.
"""

import pathlib

import streamlit as st

from core.ingest import extract_text
from core.missing import contract_types, detect_type
from storage import models
from ui.components import (
    contract_options,
    empty_state,
    finding_card,
    fmt_date,
    fmt_money,
    md_escape,
    severity_badge,
    status_badge,
)
from ui.state import load_config

SEGMENTATION_WARNING = (
    "We could not split this document into separate clauses, so clause-by-clause "
    "checks may be incomplete. Check the source file."
)

SAMPLES_DIR = pathlib.Path("data/samples")

# Risks are always listed High first so the worst findings are seen first.
_SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}

_EMPTY_MESSAGES = {
    "clause": "No clauses identified in this document.",
    "missing": "No missing clauses found for this contract type.",
    "risk": "No risk flags found in this contract.",
    "compliance": "No compliance checks apply to this contract.",
    "obligation": "No obligations or deadlines found in this contract.",
}


def sample_paths() -> list[pathlib.Path]:
    return sorted(SAMPLES_DIR.glob("*.txt"))


def friendly_name(path: pathlib.Path) -> str:
    # "service_level_agreement.txt" -> "Service level agreement".
    return path.stem.replace("_", " ").capitalize()


def default_title(text: str) -> str:
    """First non-blank line, title-cased: documents name themselves in capitals."""
    line = next((ln.strip() for ln in text.split("\n") if ln.strip()), "Untitled contract")
    return line.title()


def analyse_pending(conn) -> None:
    """Run the pipeline on the staged upload/sample and store the new version.

    On failure it shows a plain-English error and saves nothing."""
    # WHY: popped before analysing, so a document that fails is not retried
    # on every rerun and the page never gets stuck.
    pending = st.session_state.pop("pending_review")
    text, filename = pending["text"], pending["filename"]
    use_tfidf = bool(load_config()["features"].get("tfidf_fallback", False))

    try:
        with st.status("Analysing contract", expanded=False) as status:
            # WHY: lawyers distrust a silent spinner; name each step as it happens.
            status.write("Splitting clauses")
            from core.pipeline import analyse

            status.write("Checking risks and compliance")
            status.write("Extracting deadlines")
            result = analyse(text, pending["contract_type"], use_tfidf=use_tfidf)

            status.write("Saving to your register")
            contract_id = pending["contract_id"] or None
            _, version_id = models.save_analysis(
                conn, result, filename, contract_id=contract_id, title=pending["title"]
            )
            status.update(label="Analysis complete", state="complete")
    except ValueError as exc:
        # The pipeline raises ValueError with a message written for the reader,
        # e.g. an empty or scanned file.
        st.error(str(exc))
        return
    except Exception:
        st.error(
            "Something went wrong while analysing this document, so nothing was "
            "saved. Check the file and try again."
        )
        return

    st.session_state["review_version_id"] = version_id
    st.query_params["version"] = version_id
    st.toast("Analysis saved to your register", icon=":material/check:")
    st.rerun()


def upload_form(conn) -> None:
    """Upload or pick a sample, confirm type and title, then analyse."""
    uploaded = st.file_uploader(
        "Drag and drop a contract here",
        type=["pdf", "docx", "txt"],
        help="PDF, Word or plain text. The file is processed on this computer only.",
    )

    samples = sample_paths()
    names = [friendly_name(p) for p in samples]
    pick_cols = st.columns([0.8, 0.2], vertical_alignment="bottom")
    with pick_cols[0]:
        sample_name = st.selectbox("Or try a sample contract", names)
    with pick_cols[1]:
        use_sample = st.button("Use sample", icon=":material/description:", width="stretch")

    # Version control: a new upload can become the next version of a stored contract.
    # Keyed by id: two contracts can share a title (see contract_options).
    parent_labels = contract_options(models.list_contracts(conn))
    parent_id = st.selectbox(
        "Save as a new version of an existing contract (optional)",
        [None, *parent_labels.keys()],
        format_func=lambda cid: "None - this is a new contract" if cid is None else parent_labels[cid],
    )

    data, filename = None, None
    if uploaded is not None:
        data, filename = uploaded.getvalue(), uploaded.name
    elif use_sample:
        path = samples[names.index(sample_name)]
        data, filename = path.read_bytes(), path.name

    if data is None:
        return

    with st.spinner("Reading the document..."):
        try:
            text = extract_text(data, filename)
        except ValueError as exc:
            # Our own ingest errors are already plain English.
            st.error(str(exc))
            return
        except Exception:
            # WHY: a traceback means nothing to a lawyer; say what to do instead.
            st.error(
                "This file could not be read. It may be damaged, password-protected "
                "or a scan. Try a text-based PDF, a Word file or plain text."
            )
            return

    types = contract_types()
    type_ids = list(types.keys())
    detected = detect_type(text)
    contract_type = st.selectbox(
        "Contract type (auto-detected, you can change it)",
        type_ids,
        index=type_ids.index(detected) if detected in type_ids else 0,
        format_func=lambda t: types[t],
    )
    title = st.text_input("Title", value=default_title(text))

    if st.button("Analyse contract", icon=":material/play_arrow:", type="primary"):
        st.session_state["pending_review"] = {
            "text": text,
            "filename": filename,
            "contract_type": contract_type,
            "title": title.strip() or default_title(text),
            "contract_id": parent_id,
        }
        st.rerun()


def resolve_version_id(conn) -> str | None:
    """Open version: session state first, then the ?version= query param."""
    version_id = st.session_state.get("review_version_id")
    if version_id is None:
        version_id = st.query_params.get("version")
        if version_id:
            st.session_state["review_version_id"] = version_id
    if version_id and models.get_version(conn, version_id) is not None:
        return version_id
    # Stale pointer (deleted contract): forget it and show the upload form.
    st.session_state.pop("review_version_id", None)
    return None


def header_strip(conn, version: dict, contract: dict) -> None:
    """Title, badges, version number and the review progress bar."""
    reviewed, total = models.review_progress(conn, version["id"])
    with st.container(border=True):
        top, badges = st.columns([1, 0.55], vertical_alignment="center")
        with top:
            st.markdown(f"### {md_escape(contract['title'])}")
            st.caption(
                f"{contract_types().get(contract['type'], contract['type'])}"
                f" - Version {version['version_no']}"
            )
        with badges:
            status_badge(contract["status"])
        st.progress(reviewed / total if total else 0.0)
        st.caption(
            f"Reviewed {reviewed} of {total} findings. "
            "Findings are suggestions until you accept them."
        )


def _stat(label: str, value: str) -> None:
    with st.container(border=True):
        st.caption(label)
        st.markdown(f"**{md_escape(value)}**")


def summary_tab(summary: dict) -> None:
    """Extractive summary as small bordered containers, not a wall of text."""
    counts = summary["counts"]
    if summary.get("segmentation_warning"):
        # Without separate clauses the clause-by-clause checks have little to work on,
        # so say so plainly instead of letting empty tabs look like a clean contract.
        st.warning(
            "We could not split this document into separate clauses, so clause-by-clause "
            "checks may be incomplete. Check the source file.",
            icon=":material/warning:",
        )

    with st.container(border=True):
        st.markdown("**Parties**")
        if summary["parties"]:
            for party in summary["parties"]:
                name, role = md_escape(party["name"]), md_escape(party.get("role", ""))
                st.markdown(
                    f"{name}" + (f" - *{role}*" if role else ""),
                )
        else:
            st.caption("No parties identified in the preamble.")

    cols = st.columns(2)
    with cols[0]:
        _stat("Agreement date", fmt_date(summary["agreement_date"]))
        _stat("Effective date", fmt_date(summary["effective_date"]))
    with cols[1]:
        _stat("Expiry date", fmt_date(summary["expiry_date"]))
        _stat("Contract value", fmt_money(summary["value_kobo"]))

    if summary["term_text"]:
        with st.container(border=True):
            st.markdown("**Term**")
            st.markdown(md_escape(summary["term_text"]))

    if summary["key_terms"]:
        with st.container(border=True):
            st.markdown("**Key terms**")
            for term in summary["key_terms"]:
                st.markdown(
                    f"**{md_escape(term['name'])}** - {md_escape(term['sentence'])}"
                )

    with st.container(border=True):
        st.markdown("**Top risks**")
        if not summary["top_risks"]:
            st.caption("No risk flags found.")
        for risk in summary["top_risks"]:
            row = st.columns([0.3, 0.7], vertical_alignment="center")
            with row[0]:
                severity_badge(risk["severity"])
            with row[1]:
                st.markdown(md_escape(risk.get("name") or risk["label"]))

    with st.container(border=True):
        st.markdown("**Top obligations**")
        if not summary["top_obligations"]:
            st.caption("No obligations found.")
        for ob in summary["top_obligations"]:
            st.markdown(
                f"**{md_escape(ob['party'])}**"
                + (f" - {md_escape(ob['period_text'])}" if ob.get("period_text") else "")
                + f" - due {fmt_date(ob.get('due_date'))}"
            )

    cols = st.columns(4)
    with cols[0]:
        _stat("Clauses", str(counts["clauses"]))
    with cols[1]:
        _stat("High risks", str(counts["risks_high"]))
    with cols[2]:
        _stat("Missing clauses", str(counts["missing"]))
    with cols[3]:
        _stat("Obligations", str(counts["obligations"]))


def _passes_filter(finding: dict, filter_value: str) -> bool:
    if filter_value == "Needs review":
        return finding.get("status", "suggested") == "suggested"
    if filter_value == "Decided":
        return finding.get("status", "suggested") != "suggested"
    return True


def render_findings_tab(conn, version_id: str, findings: list[dict], kind: str, key_prefix: str) -> None:
    """One tab of finding cards; Risks and Clauses get a status filter."""
    items = [f for f in findings if f["kind"] == kind]
    if kind == "risk":
        items = sorted(items, key=lambda f: _SEVERITY_ORDER.get(f["severity"], 3))

    filter_value = "All"
    if kind in ("risk", "clause"):
        filter_value = st.segmented_control(
            "Filter",
            ["All", "Needs review", "Decided"],
            default="All",
            key=f"{key_prefix}-filter",
        )
    items = [f for f in items if _passes_filter(f, filter_value)]

    if not items:
        empty_state(_EMPTY_MESSAGES[kind])
        return
    for finding in items:
        finding_card(finding, version_id, conn, key_prefix)
        if kind == "compliance" and finding.get("reference"):
            st.caption(f"Reference: {md_escape(finding['reference'])}")


def tab_labels(findings: list[dict], counts: dict) -> list[str]:
    """Tab titles with live counts, e.g. 'Risks (6)'."""
    by_kind = {kind: 0 for kind in ("clause", "missing", "risk", "compliance", "obligation")}
    for finding in findings:
        by_kind[finding["kind"]] = by_kind.get(finding["kind"], 0) + 1
    return [
        "Summary",
        f"Clauses ({by_kind['clause']})",
        f"Missing clauses ({by_kind['missing']})",
        f"Risks ({by_kind['risk']})",
        f"Nigerian compliance ({by_kind['compliance']})",
        f"Obligations & deadlines ({by_kind['obligation']})",
    ]
