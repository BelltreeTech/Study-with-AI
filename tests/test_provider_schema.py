"""Wire compatibility never relaxes the post-generation domain contract."""
import copy
import json
from pathlib import Path

import pytest

from src.codex_provider import CodexProvider, ProviderError, classify_error, codex_wire_schema
from src.schemas import SCHEMAS, TEXT_SCHEMA


@pytest.mark.parametrize('schema', list(SCHEMAS.values()), ids=list(SCHEMAS))
def test_wire_projection_preserves_original_strict_contract(schema):
    original = copy.deepcopy(schema)
    wire = codex_wire_schema(schema)
    assert schema == original
    assert 'uniqueItems' not in json.dumps(wire)
    assert 'minLength' not in json.dumps(wire)
    assert 'maxLength' not in json.dumps(wire)
    assert wire['required'] == schema['required']
    assert wire['additionalProperties'] is False
    assert wire['properties'].keys() == schema['properties'].keys()


def test_property_named_unique_items_is_not_mistaken_for_schema_keyword():
    schema = {'type': 'object', 'properties': {'uniqueItems': {'type': 'boolean'}}}
    assert codex_wire_schema(schema) == schema


def test_duplicate_ids_are_still_rejected_after_valid_wire_result():
    value = {'markdown': 'Synthetic answer', 'source_ids': ['S-one', 'S-one'],
             'supplemental_markdown': '', 'insufficient_evidence': False}
    events = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(value)}},
              {'type': 'turn.completed'}]
    stdout = b''.join(json.dumps(event).encode() + b'\n' for event in events)
    with pytest.raises(ProviderError, match='形式') as error:
        CodexProvider()._parse(stdout, b'', 0, TEXT_SCHEMA)
    assert error.value.code == 'schema_error'


def test_server_schema_rejection_is_separate_from_generated_invalid_output():
    error = classify_error("Invalid schema for response_format 'codex_output_schema': uniqueItems is not permitted")
    assert error.code == 'schema_unsupported'


def test_generate_sends_compatible_schema_but_checks_original(monkeypatch):
    provider = CodexProvider()
    monkeypatch.setattr(provider, '_ensure_ready', lambda *args, **kwargs: None)
    captured = []

    def execute(args, prompt, cwd, cancel):
        wire = json.loads(Path(args[args.index('--output-schema') + 1]).read_text())
        captured.append(wire)
        value = {'markdown': 'Synthetic answer', 'source_ids': ['S-one', 'S-one'],
                 'supplemental_markdown': '', 'insufficient_evidence': False}
        events = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(value)}},
                  {'type': 'turn.completed'}]
        return b''.join(json.dumps(event).encode() + b'\n' for event in events), b'', 0

    monkeypatch.setattr(provider, '_execute', execute)
    with pytest.raises(ProviderError) as error:
        provider.generate('Synthetic prompt', TEXT_SCHEMA)
    assert error.value.code == 'schema_error'
    assert 'uniqueItems' not in captured[0]['properties']['source_ids']
    assert captured[0]['properties']['source_ids']['maxItems'] == 10
    assert TEXT_SCHEMA['properties']['source_ids']['uniqueItems'] is True
    assert TEXT_SCHEMA['properties']['markdown']['maxLength'] == 40000
