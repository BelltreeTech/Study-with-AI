"""Replay official 0.155.1 JSONL shapes; no subprocess, credentials or generation.

responses_retry.rs emits finite Reconnecting notices and a same-model transport
switch warning. App-server marks stream notices will_retry=true, but exec's
JSONL projection drops that field. Acceptance still needs successful completion.
"""

import json

import pytest

from src.codex_provider import CODE_MODE_DISABLED_WARNING, CodexProvider, ProviderError, execution_summary

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean", "enum": [True]}},
          "required": ["ok"], "additionalProperties": False}


def test_execution_summary_never_contains_raw_error_output_or_unknown_names():
    secret = "DO_NOT_PERSIST_this_token_or_student_answer"
    summary = execution_summary(wire(
        {"type": "error", "message": "unexpected status 400 Bad Request: " + secret},
        {"type": secret, "item": {"type": secret}},
    ), secret.encode(), 1)
    assert secret not in json.dumps(summary)
    assert summary["returncode"] == 1
    assert summary["events"] == {"error": 1, "unknown_event": 1}
    assert summary["signatures"] == ["bad_request"]
    assert len(summary["notices"][0]["sha256"]) == 64
COMPLETE = {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}
FINAL = {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}}


def wire(*events):
    return b"".join(json.dumps(event).encode() + b"\n" for event in events)


def warning(message):
    return {"type": "item.completed", "item": {"type": "error", "message": message}}


def test_official_disabled_code_mode_notice_is_exactly_allowlisted():
    assert CodexProvider()._parse(wire(warning(CODE_MODE_DISABLED_WARNING), FINAL, COMPLETE), b"", 0, SCHEMA) == {"ok": True}
    for text in (CODE_MODE_DISABLED_WARNING + " More warnings.", "Code Mode is unavailable for an unknown reason."):
        with pytest.raises(ProviderError):
            CodexProvider()._parse(wire(warning(text), FINAL, COMPLETE), b"", 0, SCHEMA)
    with pytest.raises(ProviderError):
        CodexProvider()._parse(wire(warning(CODE_MODE_DISABLED_WARNING)), b"", 0, SCHEMA)
    with pytest.raises(ProviderError):
        CodexProvider()._parse(wire(FINAL, COMPLETE, warning(CODE_MODE_DISABLED_WARNING)), b"", 0, SCHEMA)


def reconnect(detail="stream disconnected before completion: websocket closed by server before response.completed"):
    return {"type": "error", "message": "Reconnecting... 2/5 (" + detail + ")"}


@pytest.mark.parametrize("notice", [
    reconnect(),
    reconnect("Connection failed: connection reset by peer"),
    reconnect("request timed out"),
    reconnect("Error while reading the server response: incomplete message"),
    reconnect("unexpected status 503 Service Unavailable: temporarily unavailable"),
    warning("Falling back from WebSockets to HTTPS transport. stream disconnected before completion: websocket closed"),
    warning("Falling back from WebSockets to HTTPS transport. Connection failed: broken pipe"),
])
def test_known_finite_transport_notice_can_precede_verified_success(notice):
    assert CodexProvider()._parse(wire(notice, FINAL, COMPLETE), b"", 0, SCHEMA) == {"ok": True}


@pytest.mark.parametrize("detail", [
    "stream disconnected before completion: 401 unauthorized",
    "stream disconnected before completion: quota exceeded",
    "stream disconnected before completion: You have hit your limit",
    "stream disconnected before completion: usage not included in this plan",
    "stream disconnected before completion: model rerouted to another model",
    "stream disconnected before completion: unsupported model",
    "stream disconnected before completion: tool call blocked",
    "Connection failed: permission denied",
    "unexpected status 429 Too Many Requests: slow down",
    "unexpected status 403 Forbidden: denied",
    "unexpected status 400 Bad Request: invalid schema",
])
def test_auth_quota_model_tool_permission_and_bad_requests_are_never_recovered(detail):
    for notice in (reconnect(detail), warning("Falling back from WebSockets to HTTPS transport. " + detail)):
        with pytest.raises(ProviderError):
            CodexProvider()._parse(wire(notice, FINAL, COMPLETE), b"", 0, SCHEMA)


@pytest.mark.parametrize("notice", [
    {"type": "error", "message": "Reconnecting... waiting for network"},
    {"type": "error", "message": "Reconnecting... 6/5 (request timed out)"},
    {"type": "error", "message": "Reconnecting... 2/7 (request timed out)"},
    {"type": "error", "message": "Reconnecting... 2/5 (unknown failure)"},
    {"type": "error", "message": "Reconnecting... 2/5 (request timed out)\nother event"},
    warning("Unknown configuration warning"),
    warning("model rerouted: gpt-6-astra -> another (capacity)"),
    warning("Falling back to another provider"),
])
def test_unknown_warning_and_unbounded_reconnect_are_rejected(notice):
    with pytest.raises(ProviderError):
        CodexProvider()._parse(wire(notice, FINAL, COMPLETE), b"", 0, SCHEMA)


@pytest.mark.parametrize(("events", "returncode", "code"), [
    ([reconnect(), FINAL, COMPLETE], 1, None),
    ([reconnect(), FINAL], 0, "incomplete_output"),
    ([reconnect(), COMPLETE], 0, "incomplete_output"),
    ([reconnect(), {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":false}'}}, COMPLETE], 0, "schema_error"),
    ([reconnect(), {"type": "turn.failed", "error": {"message": "connection failed"}}, FINAL, COMPLETE], 0, "network_error"),
    ([FINAL, COMPLETE, reconnect()], 0, None),
])
def test_transport_notice_never_replaces_exit_completion_or_schema_requirements(events, returncode, code):
    with pytest.raises(ProviderError) as error:
        CodexProvider()._parse(wire(*events), b"", returncode, SCHEMA)
    if code is not None:
        assert error.value.code == code


@pytest.mark.parametrize("tool_type", ["command_execution", "mcp_tool_call", "web_search", "file_change", "collab_tool_call", "todo_list"])
def test_tool_events_are_rejected_even_with_transport_recovery(tool_type):
    tool = {"type": "item.completed", "item": {"type": tool_type}}
    with pytest.raises(ProviderError) as error:
        CodexProvider()._parse(wire(reconnect(), tool, FINAL, COMPLETE), b"", 0, SCHEMA)
    assert error.value.code == "tool_violation"
