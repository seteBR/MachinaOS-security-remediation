"""Security regressions for generic webhook trigger dispatch."""

from __future__ import annotations

from services.event_waiter import build_webhook_filter


def test_webhook_filter_enforces_method() -> None:
    matches = build_webhook_filter({"path": "hook", "method": "POST"})

    assert matches({"path": "hook", "method": "POST", "headers": {}})
    assert not matches({"path": "hook", "method": "GET", "headers": {}})


def test_webhook_filter_allows_any_method_when_configured() -> None:
    matches = build_webhook_filter({"path": "hook", "method": "ALL"})

    assert matches({"path": "hook", "method": "GET", "headers": {}})
    assert matches({"path": "hook", "method": "PATCH", "headers": {}})


def test_webhook_filter_enforces_header_auth_case_insensitively() -> None:
    matches = build_webhook_filter(
        {
            "path": "hook",
            "method": "POST",
            "authentication": "header",
            "header_name": "X-Webhook-Secret",
            "header_value": "expected-secret",
        }
    )

    assert matches(
        {
            "path": "hook",
            "method": "POST",
            "headers": {"x-webhook-secret": "expected-secret"},
        }
    )
    assert not matches(
        {
            "path": "hook",
            "method": "POST",
            "headers": {"x-webhook-secret": "wrong-secret"},
        }
    )


def test_webhook_filter_header_auth_fails_closed_without_expected_value() -> None:
    matches = build_webhook_filter(
        {
            "path": "hook",
            "method": "POST",
            "authentication": "header",
            "header_name": "X-Webhook-Secret",
            "header_value": "",
        }
    )

    assert not matches(
        {
            "path": "hook",
            "method": "POST",
            "headers": {"x-webhook-secret": "anything"},
        }
    )
