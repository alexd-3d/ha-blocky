# Changelog

## 0.9.0

### Added

- **Overview card** (BLO-012): `custom:ha-blocky-overview-card` shows the top
  domains, top blocked domains and top clients of the last 24 hours with their
  counts, and the requests waiting for a decision, with icon actions (Block on a
  top domain, Allow on a top blocked domain, Approve/Reject or Block/Dismiss on a
  request). Clients are named and renamed as in the query log. It replaces the
  markdown tables over the top-list sensors. It reloads every 60 seconds
  (`auto_refresh`, 0 turns it off) and after each action.
- **Known domains** in the Requests tab: every tracked client has a collapsible
  list of its known domains, loaded when expanded, newest first (up to 200). A
  client of a learning zone gets a Block icon per domain (first deny list of its
  zone). The list of a client of an allowlist-only zone is read-only.
- Query log: "Group repeats" (on by default, not remembered) merges rows of the
  loaded pages with the same client, domain, type and status into one line with
  `×N` and the latest time.
- WebSocket commands `ha_blocky/overview`, `ha_blocky/known_domains` and
  `ha_blocky/block_known` (administrators only). They are internal to the cards.
  The answer of `ha_blocky/requests` has a new `tracked` list.
- README: dashboard snippets for the overview card and for a chart period
  switcher (the `select-options` tile feature is not verified on 2026.10.4; a
  button-card fallback is given).

### Changed

- Allow and Block in the query log are icon buttons (`ha-icon`, keyboard
  focusable, with a hover text) and a row offers one action: Block on an answered
  or cached row, Allow on a blocked row.
- In a narrow card (about 560 px or less) a log entry takes two lines: client and
  domain, then time, status icon and the action icon; Type and ms are hidden.

### Security

- The new commands check their input strictly: a client must be an IP address,
  a domain one exact name (no wildcard), both in canonical form, and
  `block_known` only acts on a tracked client of a learning zone and a domain
  that client already knows. Answers name no log data in errors.
- Icon names come from two fixed tables in the card; no icon, label or hover text
  is taken from data. Values from the server are still shown with `textContent`.

## 0.8.0

### Added

- **Client names** (BLO-011): a client is shown by name. Order: a name you typed
  (click the client in the card; Enter saves, Escape cancels, empty clears;
  stored by Home Assistant, up to 512, keyed by IP address), then the friendly
  name of a `device_tracker` whose `ip` attribute is the address, then none.
  `client_name` is added next to the client in the query log and requests
  answers, in the `get_requests` action answer and in the events
  `ha_blocky_new_domain`, `ha_blocky_unexpected_domain`, `ha_blocky_zone_leak`
  and `ha_blocky_new_domains_summary`.
- **Sidebar panel**: an administrator-only HA-Blocky panel with the card full
  width. Option "Show in sidebar" (on by default).
- WebSocket command `ha_blocky/set_client_name` (administrators only), used by
  the card. It is internal to the card.
- Diagnostics show how long the last new-domain baseline query took.

### Changed

- The card no longer looks at device trackers in the browser; names come from
  the server. The card is split into several JavaScript files served from
  `/ha_blocky/` (the card address `/ha_blocky/ha-blocky-card.js` is unchanged).
- The client cell shows the name (or the address) first, and the zone and the
  address smaller below.

### Security

- Names, from a person or from a device tracker, are checked: stripped, 1 to 64
  characters, no control, format, private-use or unassigned characters, no line
  or paragraph separators. A bad name is refused (typed) or ignored (tracker).
  Names are shown with `textContent` only and are never written to diagnostics
  or logs.

## 0.7.0

### Added

- **New-domain tracking** (BLO-010): the clients of `learning` and
  `allowlist_only` zones are watched through the query log. A new domain fires
  `ha_blocky_new_domain` and creates a request (24 hours, single use) that you
  approve, reject or block. Locked clients of an allowlist-only zone fire
  `ha_blocky_unexpected_domain`; answers for domains on none of a zone's allow
  lists fire `ha_blocky_zone_leak` and drive a problem sensor. Per client at
  most 5 events per 10 minutes, then one `ha_blocky_new_domains_summary`.
  - Actions: `approve_request`, `reject_request`, `block_request`,
    `get_requests`, `set_client_phase`.
  - A pending-requests sensor and a zone leak sensor.
  - Option "Report existing history as new"; by default a new client of a
    learning zone starts with its last 7 days taken as known.
  - A Requests tab in the query log card, with client phases and device names.
  - Example Telegram blueprint in `blueprints/automation/ha_blocky/`.

### Security

- Names read from the log are validated, client addresses must be IP addresses,
  all state is capped and validated again on load, and diagnostics show counts
  only.

## 0.6.0

### Added

- **Zones**: named groups of client addresses or networks, defined under
  Configure → Zones. Each zone has a mode (`filter`, `learning` or
  `allowlist_only`) and linked manual lists. A zone is only a record used to
  tell which policy applies to a client seen in the query log; the
  integration never changes Blocky's configuration.
  - Up to 16 zones with up to 8 networks each. Zones must not overlap,
    because Blocky merges the groups of every match, which would silently
    switch an allowlist-only group off.
  - An `allowlist_only` zone needs at least one linked list, and only allow
    lists marked "exact domains only" are accepted.
  - A manual list that a zone uses cannot be removed or changed in a way
    that breaks the zone.
- **Blocky configuration for zones**: a ready fragment (`denylists`,
  `allowlists`, `clientGroupsBlock`) to copy into the Blocky configuration.
- Two sensors per zone: queries and blocked queries in the last 24 hours.
- The query log card shows the zone of each client.

### Security

- Zone networks never appear in diagnostics, logs or the card's
  configuration data.
- Stored zones are validated again on every read; an invalid one is ignored.

## 0.5.0

### Added

- **Query log card** (`custom:ha-blocky-card`). The integration registers it
  itself; add it from the dashboard card picker as "HA-Blocky query log".
  - Search by domain and by client address, filter by status and period.
  - Click a column header to sort the loaded rows; "Load more" fetches the
    next page.
  - **Allow** and **Block** buttons on each row add the domain to one of the
    manual lists.
  - Options: `title`, `entry_id`, `page_size` (10 to 200, default 50) and
    `auto_refresh` in seconds (off by default, at least 10).
  - English and Ukrainian texts.
- Running totals by kind of answer: **Resolved queries**, **Cached
  queries**, **Locally answered queries** and **Other queries**, next to
  the existing **Blocked queries**. Every query is counted in exactly one
  of the five, so they can be stacked in one bar per period.

### Security

- The card and its two WebSocket commands are for administrators only.
- Values from the log are always shown as plain text and never interpreted
  as markup. The card loads nothing from outside Home Assistant.
- The domain search is literal: `%` and `_` match themselves.

## 0.4.0

### Added

- Manual allow and deny lists, managed from Home Assistant and downloaded by
  Blocky:
  - Define any number of named lists in **Configure → Manual lists**. A list
    can be marked as accepting only exact domain names, without wildcards.
  - Actions `ha_blocky.allow_domain`, `ha_blocky.block_domain`,
    `ha_blocky.remove_domain` and `ha_blocky.get_list`. Blocky is asked to
    reload its lists once, shortly after the last change.
  - **Configure → List addresses for Blocky** shows the address of each list
    to add as a source in Blocky's configuration.
  - A sensor per list with the number of entries.
  - The `ha_blocky_list_changed` event records every change together with
    the user who made it.
- Update intervals in **Configure → Update intervals**: blocking status,
  query counters and top lists.

### Changed

- The **Configure** dialog is now a menu.

### Security

- Lists are served from the integration's only endpoint without a Home
  Assistant login, because Blocky cannot log in. Access needs a 256-bit token
  in the address and a client inside the configured networks; by default only
  Home Assistant apps (add-ons) qualify. The token can be replaced with
  `ha_blocky.rotate_list_token`.
- List entries are limited to domain names and an optional leading `*.`.
  Blocky's regular expressions and entries broader than a domain are refused.
- All list actions are restricted to administrators.

## 0.3.0

### Added

- Optional query log database. In the integration's **Configure** dialog,
  connect to the MySQL or MariaDB database Blocky writes its query log to.
  The account must be read-only: an account that can change data is refused.
- Statistics sensors, available once the database is connected:
  - **Queries** and **Blocked queries**: running totals that work with
    Home Assistant's long-term statistics.
  - For the last 24 hours: **Queries**, **Blocked queries**, **Blocked share**,
    **Clients** and **Average response time**.
  - **Top domains**, **Top blocked domains** and **Top clients**, with the ten
    most frequent entries as attributes. The lists are not written to the
    recorder.
- **Query log database** binary sensor showing whether the database answers.
- Diagnostics download, with addresses, credentials, domain names and client
  addresses left out.

### Notes

- A database outage only affects the statistics sensors. Controlling Blocky
  keeps working.
- The running totals start at zero when the database is first connected; the
  existing log is not added to them.

## 0.2.0

### Added

- A device with six entities:
  - **Blocking** switch. Turning it off pauses blocking for 5 minutes; it never
    disables blocking indefinitely.
  - **Pause blocking** select. Choosing a duration (5, 15 or 30 minutes, 1, 2 or
    4 hours) pauses blocking for that long right away; choosing "Not paused"
    resumes it.
  - **Blocking resumes at** sensor.
  - **Connection** binary sensor, which stays available while Blocky is down so
    an outage is visible.
  - **Refresh lists** and **Flush cache** buttons.
- The `ha_blocky.disable_blocking` action for automations, with a mandatory
  duration (up to 24 hours) and optional groups. Administrators only.
- The `ha_blocky_blocking_disabled_externally` event, fired when blocking is
  disabled or reduced by something other than this integration.

## 0.1.0

### Added

- Set up the integration from the Home Assistant UI by entering the Blocky API
  URL. The connection is verified before the entry is created, and the same
  Blocky instance cannot be added twice.
- English and Ukrainian translations.

This release only connects to Blocky. It does not provide entities or actions
yet.
