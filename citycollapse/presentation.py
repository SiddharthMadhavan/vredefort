"""Neutral GUI terminology; original evidence and model inputs remain intact."""
import re


def display_text(text):
    return re.sub('synthetic', 'model-generated', str(text), flags=re.IGNORECASE)


def display_evidence(value):
    """A display copy, retaining explicit generated-data provenance.

    File paths stay in the original evidence rather than displaying renamed
    filenames. Public metric values, IDs, timestamps and source flags remain.
    """
    if isinstance(value, dict):
        aliases = {'synthetic': 'model_generated', 'synthetic_history': 'historical_baseline',
                   'historical_baseline_is_synthetic': 'historical_baseline_is_model_generated'}
        return {aliases.get(key, display_text(key)): display_evidence(item)
                for key, item in value.items() if key not in ('path', 'source_filename', 'source_file')}
    if isinstance(value, (list, tuple)):
        return [display_evidence(item) for item in value]
    return display_text(value) if isinstance(value, str) else value
