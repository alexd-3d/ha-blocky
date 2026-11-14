"""HTTP endpoint Blocky fetches the manual lists from.

This is the integration's only unauthenticated endpoint. Blocky cannot log
in to Home Assistant, so access is granted by a 256-bit token in the path
and limited to configured client networks. The lists it serves contain
domain names only.

The optional query value ``r`` is the revision marker of the configuration the
list address was rendered for. It is recorded (in memory, fixed list names
only) when it is exactly 8 lower-case hex characters and otherwise ignored:
never echoed, never logged, and it changes neither the body nor the status.
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .levels import valid_rev
from .lists import find_list_body


class BlockyListView(HomeAssistantView):
    """Serve a manual list as plain text."""

    url = f"/api/{DOMAIN}/lists/{{token}}/{{filename}}"
    name = f"api:{DOMAIN}:lists"
    requires_auth = False
    cors_allowed = False

    async def get(
        self, request: web.Request, token: str, filename: str
    ) -> web.Response:
        """Return the list, or the same 404 for every kind of refusal."""
        hass = request.app[KEY_HASS]
        managers = [
            entry.runtime_data.lists
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
        rev = valid_rev(request.query.get("r"))
        body = find_list_body(managers, request.remote, token, filename, rev)
        if body is None:
            return web.Response(status=404)
        return web.Response(
            text=body,
            content_type="text/plain",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )


@callback
def async_register_view(hass: HomeAssistant) -> None:
    """Register the list endpoint."""
    hass.http.register_view(BlockyListView())
