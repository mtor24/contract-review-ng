"""Shared spaCy pipeline for clause classification."""

import functools

import spacy


@functools.lru_cache(maxsize=None)
def get_nlp():
    # We only need tokens/lemmas for PhraseMatcher, so disabling ner and parser
    # keeps the pipeline fast without affecting matching.
    return spacy.load("en_core_web_sm", disable=["ner", "parser"])
