# LexReview NG

LexReview NG is a contract review and management prototype for Nigerian law firms. We built it as the design artefact for our Master's capstone project, "AI-Driven Contract Review and Management System Developed with Python NLP Libraries for Nigerian Law Firms", at the European Global Institute of Innovation and Technology and Docenti Global Business School.

It reads a contract, splits it into clauses, labels them, points out missing clauses and risky wording, runs indicative Nigerian compliance checks, lists obligations and deadlines, and keeps everything in a searchable local register. Every result is a suggestion that a lawyer can accept, reject or edit.

> Assists contract review. Does not give legal advice.

## Why it looks the way it does

We surveyed 321 Nigerian legal practitioners before writing any code. Their answers set our priorities: clause identification (96.9% wanted it), missing clause detection (93.2%), risk analysis (93.1%) and compliance checking (87.2%) came first. Their biggest worries were data privacy (85%) and confidentiality (84.4%), and 88.5% said AI should support lawyers rather than replace them.

So we made three firm decisions:

1. **Everything runs on your computer.** No contract text is ever sent to an external API or cloud model, and there is no telemetry.
2. **The lawyer decides.** Every finding shows the sentence it came from and stays a "Suggestion" until a lawyer accepts, rejects or edits it.
3. **The logic is readable.** We used rules and spaCy pattern matching rather than a black-box model, and every rule lives in a YAML file with plain-English comments.

## Features

- Upload PDF, Word or plain text contracts (drag and drop)
- Automatic contract type detection: employment, commercial supply, lease, NDA, partnership, service level and loan agreements
- Clause splitting for "1.", "1.1", "(a)", "Clause 5" and heading-style contracts
- Clause identification across 19 clause types
- Missing clause detection against a checklist for each contract type
- Risk flags with High, Medium or Low severity and a plain-English reason
- Indicative Nigerian compliance checks (Nigerian governing law, Nigeria Data Protection Act 2023, Arbitration and Mediation Act 2023, stamp duty reminders, Labour Act points for employment contracts)
- Obligations and deadlines, converted to calendar dates where the contract gives an anchor date
- Extractive summary: parties, dates, value, term, key terms, top risks and obligations
- A two-pane review workspace: click "Show in text" on any finding to jump to its sentence
- Contract register with status tracking, a 30, 60 and 90 day deadlines view, and keyword search
- Version history with a side-by-side clause comparison
- PDF and Word review reports that include the lawyer's decisions
- Optional password lock, delete one contract or all data, no telemetry
- Optional TF-IDF fallback for clauses the rules cannot label (off by default)

## Getting started

You need Python 3.11. An internet connection is only needed once, to install the packages. After that the app works fully offline.

```bash
git clone https://github.com/mtor24/contract-review-ng.git
cd contract-review-ng

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS or Linux
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser at http://localhost:8501. The spaCy English model (`en_core_web_sm`) is installed by `requirements.txt`, so there is no separate download step.

## Trying it out

1. Open **Settings** and click **Load sample contracts**, or go to **Review a Contract** and pick a sample from the list.
2. Open a contract in **Review a Contract**. The left pane shows the contract with clauses tinted by type and risky sentences highlighted. The tabs on the right hold the summary, clauses, missing clauses, risks, compliance checks and obligations.
3. Accept, reject or edit a few findings and add a note. The progress bar updates as you go.
4. Look at **Deadlines**, try **Search** with a word such as "indemnify", and export a report from **Reports**.
5. To see version comparison, upload `data/samples/versions/supply_agreement_v2.txt` as a new version of the supply agreement, then open it in the **Contract Register**.

`docs/demo.md` walks through every feature in order, with screenshots.

The seven sample contracts in `data/samples/` are synthetic. We wrote them for this project, with fictional Nigerian companies, Lagos and Abuja addresses and Naira amounts, and we planted risky and missing clauses in them on purpose so the demo shows every feature. `data/samples/expected.yaml` lists what we planted, and the tests check that the system finds it.

## Changing the rules

All of the legal logic lives in four YAML files, and each one starts with comments explaining how to edit it:

| File | What it controls |
|------|------------------|
| `rules/clause_patterns.yaml` | Heading keywords and phrases for each of the 19 clause types |
| `rules/checklists.yaml` | Which clauses each contract type should contain, and why |
| `rules/risk_rules.yaml` | The 12 risk rules, their severity and their plain-English reasons |
| `rules/nigeria_compliance.yaml` | The 7 indicative Nigerian compliance checks |

Restart the app after editing a rules file.

## Project layout

```
app.py                Streamlit entry point
core/                 analysis modules (ingest, segment, classify, missing, risk,
                      compliance, obligations, summarise, diff, report, pipeline)
storage/              SQLite schema and queries
rules/                editable YAML rules
ui/                   pages, shared components, text highlighter, lock screen
data/samples/         synthetic sample contracts
data/training/        synthetic examples for the optional TF-IDF fallback
tests/                pytest tests
docs/                 architecture, demo script and screenshots
```

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests cover segmentation, classification, missing clause detection, every risk rule, compliance checks, date and deadline extraction, storage (including deletion and search), version comparison, reports, the text highlighter and a smoke test of every page. GitHub Actions runs them on every push.

## Privacy and data

- Contracts, findings and decisions are stored in one file, `data/lexreview.db`, on your computer. It is excluded from Git.
- The app only accepts connections from your own computer, not from other machines on the network.
- Deleting a contract removes its text from the database file completely, including the search index.
- Settings changes, including the optional password hash, are saved to `data/local_config.yaml`, which is also excluded from Git.
- The password is never stored, only a salted scrypt hash of it.
- You can delete a single contract and everything linked to it from the Contract Register, or delete all data from Settings.

## Limitations

This is a research prototype, not a finished product. In short: we demonstrate it on synthetic contracts and have not formally measured its accuracy; rule-based labels can miss unusual drafting; scanned PDFs need OCR, which we do not include; deadlines are only dated when the contract states an anchor date; compliance checks are indicative and do not interpret the law; and it is a single-user tool without encryption at rest. `docs/architecture.md` explains each of these in more detail.

## Licence

MIT. See `LICENSE`. Copyright 2026 Capstone Project Group 4.
