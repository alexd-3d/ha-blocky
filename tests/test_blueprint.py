"""Checks of the example Telegram blueprint (static; it is never run here)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

BLUEPRINT = (
    Path(__file__).resolve().parent.parent
    / "blueprints"
    / "automation"
    / "ha_blocky"
    / "telegram_requests.yaml"
)
ID_PATTERN = "^[A-Za-z0-9_-]{16,64}$"


class _Loader(yaml.SafeLoader):
    """A loader that keeps ``!input x`` as a plain marker."""


_Loader.add_constructor(
    "!input", lambda loader, node: {"!input": loader.construct_scalar(node)}
)


def _load() -> dict[str, Any]:
    return yaml.load(BLUEPRINT.read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506


def _walk(node: Any):  # type: ignore[no-untyped-def]
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _callback_branch(blueprint: dict[str, Any]) -> dict[str, Any]:
    for option in blueprint["actions"][0]["choose"]:
        if any(c.get("id") == "callback" for c in option["conditions"]):
            return option
    raise AssertionError("no callback branch")


def test_blueprint_parses_and_belongs_to_this_repository() -> None:
    blueprint = _load()

    assert blueprint["blueprint"]["domain"] == "automation"
    source = blueprint["blueprint"]["source_url"]
    assert source.startswith("https://github.com/alexd-3d/ha-blocky/")
    urls = re.findall(r"https?://\S+", BLUEPRINT.read_text(encoding="utf-8"))
    assert all(url.startswith("https://github.com/alexd-3d/ha-blocky/") for url in urls)


def test_all_events_trigger_it() -> None:
    triggers = _load()["triggers"]

    assert {t["event_type"] for t in triggers} == {
        "ha_blocky_new_domain",
        "ha_blocky_unexpected_domain",
        "ha_blocky_zone_leak",
        "ha_blocky_new_domains_summary",
        "telegram_callback",
    }


def test_allowed_user_ids_is_required_and_has_no_default() -> None:
    inputs = _load()["blueprint"]["input"]

    assert {"requests_chat_id", "alarms_chat_id", "allowed_user_ids"} <= set(inputs)
    assert "default" not in inputs["allowed_user_ids"]
    assert inputs["allowed_user_ids"]["selector"]["text"]["multiple"] is True


def test_callback_branch_checks_user_command_and_request_id() -> None:
    branch = _callback_branch(_load())
    templates = " ".join(
        c["value_template"] for c in branch["conditions"] if "value_template" in c
    )

    assert "allowed_users | length > 0" in templates
    assert "trigger.event.data.user_id" in templates
    assert ID_PATTERN in templates
    for word in ("/blocky_approve", "/blocky_reject", "/blocky_block"):
        assert word in templates
    # Nothing in the branch runs before all conditions: it is the conditions.
    assert len(branch["conditions"]) >= 4
    services = {
        a["action"]
        for a in _walk(branch["sequence"])
        if isinstance(a, dict) and "action" in a
    }
    assert services == {
        "ha_blocky.approve_request",
        "ha_blocky.reject_request",
        "ha_blocky.block_request",
        "telegram_bot.answer_callback_query",
    }


def test_messages_are_plain_text_and_buttons_carry_command_and_id() -> None:
    blueprint = _load()
    sends = [
        a
        for a in _walk(blueprint["actions"])
        if isinstance(a, dict) and a.get("action") == "telegram_bot.send_message"
    ]

    assert len(sends) == 3
    for send in sends:
        assert send["data"]["parse_mode"] == "plain_text"
    keyboards = [
        s["data"]["inline_keyboard"] for s in sends if "inline_keyboard" in s["data"]
    ]
    assert len(keyboards) == 1
    # Callback data: a fixed command word, a space and the request id.
    assert "command[name] ~ ' ' ~ trigger.event.data.request_id" in keyboards[0]
    assert len("/blocky_approve " + "x" * 22) <= 64
    text = BLUEPRINT.read_text(encoding="utf-8")
    for other in ("markdown", "html", "markdownv2"):
        assert f"parse_mode: {other}" not in text.lower()


async def test_keyboard_and_checks_render_as_intended(hass: Any) -> None:
    from homeassistant.helpers.template import Template

    blueprint = _load()
    send = blueprint["actions"][0]["choose"][0]["sequence"][0]
    request_id = "A1b2C3d4E5f6G7h8I9j0K_"
    event = {
        "request_id": request_id,
        "actions": ["approve", "reject", "bogus"],
    }
    keyboard = Template(send["data"]["inline_keyboard"], hass).async_render(
        {"trigger": {"event": {"data": event}}}
    )
    assert keyboard == [
        [
            ["Approve", f"/blocky_approve {request_id}"],
            ["Reject", f"/blocky_reject {request_id}"],
        ]
    ]

    branch = _callback_branch(blueprint)
    user, command, ids = (branch["conditions"][i]["value_template"] for i in (1, 2, 3))

    def check(template: str, data: dict[str, Any], users: list[str]) -> Any:
        variables = {
            "trigger": {"event": {"data": data}},
            "allowed_users": users,
        }
        return Template(template, hass).async_render(variables)

    assert check(user, {"user_id": 42}, ["42"]) is True
    assert check(user, {"user_id": 43}, ["42"]) is False
    assert check(user, {"user_id": 42}, []) is False
    assert check(command, {"command": "/blocky_block"}, []) is True
    assert check(command, {"command": "/start"}, []) is False
    assert check(ids, {"args": [request_id]}, []) is True
    for bad in (["short"], [request_id, "x"], [], ["bad id" + "x" * 20], ["a" * 65]):
        assert check(ids, {"args": bad}, []) is False
