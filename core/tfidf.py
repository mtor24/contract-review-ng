"""Optional TF-IDF fallback classifier for clauses the rules label "other".

OFF by default: nothing here runs unless the caller passes use_tfidf=True
through classify() or analyse(). The model is trained in memory at first
use from the small SYNTHETIC labelled set in data/training/clauses.yaml.
No model files are written to disk: training takes under a second, and
keeping everything in memory means there is no pickle for anyone to
tamper with. This is a SUGGESTION layer only; the rule-based classifier
in core/classify.py remains the primary authority.
"""

import functools
from pathlib import Path

import yaml
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

# Training data lives next to the other editable data files, not inside core/.
TRAINING_PATH = Path(__file__).resolve().parent.parent / "data" / "training" / "clauses.yaml"


def train(examples: list[dict]) -> Pipeline:
    """Train a TF-IDF + calibrated linear SVM pipeline on labelled examples.

    examples: list of {"label": <label id>, "text": <clause text>}.
    """
    texts = [e["text"] for e in examples]
    labels = [e["label"] for e in examples]
    model = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    # Unigrams + bigrams because legal meaning often sits in
                    # short phrases ("return or destroy"); sublinear_tf keeps
                    # repetition in long clauses from dominating.
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                    min_df=1,
                    stop_words="english",
                ),
            ),
            (
                "clf",
                # A linear SVM gives sharper margins than plain logistic
                # regression on tiny sets; CalibratedClassifierCV turns those
                # margins into probabilities (Platt scaling) so a confidence
                # threshold can be applied. Balanced weights keep it safe if
                # a lawyer tops up only some labels, and the fixed seed makes
                # the same training file give the same suggestions.
                CalibratedClassifierCV(
                    LinearSVC(class_weight="balanced", random_state=42),
                    cv=3,
                ),
            ),
        ]
    )
    model.fit(texts, labels)
    return model


@functools.lru_cache(maxsize=1)
def get_model() -> Pipeline:
    """Train (once per process) on data/training/clauses.yaml and return it."""
    with TRAINING_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return train(data["examples"])


def suggest(texts: list[str], threshold: float = 0.45) -> list[tuple[str | None, float]]:
    """Predict a label per text; (None, prob) when the best class is below
    threshold, so weak guesses stay "other" instead of adding noise."""
    if not texts:
        return []
    model = get_model()
    probas = model.predict_proba(texts)
    classes = model.classes_
    results = []
    for row in probas:
        best = row.argmax()
        label, prob = str(classes[best]), float(row[best])
        results.append((label, prob) if prob >= threshold else (None, prob))
    return results
