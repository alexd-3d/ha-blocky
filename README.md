# HA-Blocky

A Home Assistant custom integration for the [Blocky](https://github.com/0xERR0R/blocky)
DNS proxy and ad-blocker.

> **Status: early development.** The integration can pause and resume blocking,
> refresh lists, flush the cache, report whether Blocky is reachable, show
> statistics from Blocky's query log database, manage manual allow and deny
> lists, see a dashboard and browse the query log in a card or a sidebar panel, name clients
> and handle requests for new domains.

## Goals

- Control Blocky from Home Assistant: enable or pause blocking, refresh lists,
  flush the cache.
- Show what the DNS filter is doing: query counters, blocked ratio, top domains
  and clients, and a searchable query log read from Blocky's database log.
- Manage manual allow and deny lists from Home Assistant, per client group.
- Support allowlist-only client groups with an approval workflow, so a new
  device can only reach domains that were explicitly approved.
- Expose events and actions so approvals can be driven from automations.

## Comparison

How Blocky with HA-Blocky compares with two well-known DNS filters. The Blocky column
describes Blocky v0.35 itself plus what this integration adds on top of it. Cells marked
"not documented" mean the feature is not mentioned in Blocky's documentation; check the
current documentation of each project before relying on this table.

| Feature | AdGuard Home | Pi-hole | Blocky + HA-Blocky |
|---|---|---|---|
| Blocking ads and trackers | ✅ | ✅ | 🟡 Through lists that you add to Blocky's configuration |
| Customizing blocklists | ✅ | ✅ | ✅ Blocky list groups, plus manual allow and deny lists managed from Home Assistant |
| Built-in DHCP server | ✅ | ✅ | ❌ |
| HTTPS for the admin interface | ✅ | ✅ | ➖ No admin interface of its own: the card lives inside Home Assistant (administrators only). Blocky's HTTP API has no authentication |
| Encrypted DNS upstream servers | ✅ DoH, DoT, DNSCrypt | ❌ Requires additional software | ✅ DoH and DoT (DNSCrypt not documented) |
| Cross-platform | ✅ | ❌ Not natively, only via Docker | ✅ Single Go binary or container; the integration needs Home Assistant 2026.10 or newer |
| Running as a DoH or DoT server | ✅ | ❌ Requires additional software | ✅ |
| Blocking phishing and malware domains | ✅ | 🟡 Requires non-default blocklists | 🟡 Add a malware or phishing list, same as for ads |
| Parental control (blocking adult domains) | ✅ | 🟡 Requires non-default blocklists | 🟡 Add an adult-content list to the client group that needs it |
| Force safe search on search engines | ✅ | ❌ | Not documented |
| Per-client (device) configuration | ✅ | ✅ | ✅ Client groups in Blocky; zones with `filter`, `learning` and `allowlist_only` modes |
| Access settings (who can use the DNS) | ✅ | ❌ | Not documented |
| Approval workflow for new domains | ❌ | ❌ | ✅ Requests with Approve, Reject and Block |
| Allowlist-only zones with leak detection | ❌ | ❌ | ✅ |
| Events and actions for automations | ❌ | ❌ | ✅ Home Assistant events and actions |

The AdGuard Home and Pi-hole columns are based on the table in the AdGuard Home
documentation and have not been re-checked against current Pi-hole releases.

## Recommended network setup

A DNS filter only helps while clients actually use it. HA-Blocky does not configure your
router or Blocky, and it does not detect clients that bypass the filter. It works best
with this setup, which you build yourself:

1. **Send all home DNS through Blocky.** Hand out Blocky as the DNS server by DHCP, and
   redirect port 53 (UDP and TCP) from clients to Blocky on your router, so devices with
   a built-in DNS server still end up at the filter.
2. **Encrypt the way out.** Configure Blocky's upstream resolvers as DNS-over-HTTPS or
   DNS-over-TLS, so queries are not readable on the path to the resolver.
3. **Block or log bypasses.** Drop or at least log outbound DNS-over-TLS (port 853) from
   clients to the internet. DNS-over-HTTPS shares port 443 with normal web traffic and
   direct connections to an IP address never ask DNS at all; both can only be limited
   with a list of known DoH servers or an allowlist on the router, not by Blocky.

Zone leak detection (see above) is related but different: it reports answers Blocky gave
for domains outside an `allowlist_only` zone's allow lists.

## Design principles

- **Zero trust.** Every input is treated as hostile, including domain names read
  from the DNS query log, API responses and database rows.
- **Least privilege.** The integration only needs read access to the query log
  database. Actions and data access are limited to Home Assistant administrators.
- **Fail closed.** A failure of the integration must never disable filtering or
  open an allowlist-only group.
- **Minimal dependencies.** No frontend build step and no third-party frontend
  packages.
- **Nothing network-specific in the code.** Client groups, subnets and lists are
  configured by the user.

## Zones

A zone is a named group of client networks that you define in the integration
options. It is only a record kept in Home Assistant, used to tell which policy
applies to a client seen in the query log: the query log card labels each client
with its zone, and each zone gets 24 hour query and blocked-query sensors. A zone
has one of three modes: `filter` (filtered as usual), `learning` (filtered as
usual, meant for watching which domains its clients ask for) or `allowlist_only` (only the linked allow
lists without wildcards). Zones must not overlap. The integration never edits
Blocky's configuration: the options show a configuration fragment for you to
copy into it.

## New-domain tracking

With the query log database configured, the integration watches the clients of
`learning` and `allowlist_only` zones and turns what they ask for into events and
requests. Nothing is tracked for `filter` zones or for clients outside every zone.

**Zone modes and phases**

- `learning` zone: the first time a client asks for a domain, the integration fires
  `ha_blocky_new_domain` and creates a request with the actions Block and Dismiss.
  Block adds the exact domain to the first deny list linked to the zone (an error if
  the zone has none). Dismiss only closes the request. Either way the pair of client
  and domain is known from then on.
- `allowlist_only` zone: every client has a phase, `learning` (the default for a new
  client) or `locked`. In the learning phase, a new domain whose answer was blocked
  creates a request with the actions Approve and Reject and fires
  `ha_blocky_new_domain`. Approve adds the exact domain to the first allow list of the
  zone, or to the allow list named in the call (it must be one of the zone's allow
  lists). Reject remembers the pair, which then never raises a request again. A locked
  client raises no request; a new blocked domain fires `ha_blocky_unexpected_domain`,
  once per pair. The phase changes only through the `ha_blocky.set_client_phase`
  action.

**Life cycle of a request.** A request has a random id, is single use and expires
after 24 hours. When a request expires in a `learning` zone, the pair is treated as
known; in an `allowlist_only` zone it is not, so the next blocked query raises a new
request. At most 200 requests are pending; beyond that no new request is created.
Per client at most 1000 known and 500 rejected pairs are kept (the least recently
seen are forgotten first), and at most 256 clients are tracked.

**Actions** (administrators only)

- `ha_blocky.approve_request`: `request_id`, optional `list`.
- `ha_blocky.reject_request`: `request_id` (in a learning zone this is Dismiss).
- `ha_blocky.block_request`: `request_id`, learning zones only.
- `ha_blocky.get_requests`: returns the pending requests and the client phases.
- `ha_blocky.set_client_phase`: `client` (IP address), `phase` (`learning` or `locked`).

All of them accept an optional `config_entry_id` when more than one Blocky instance is
set up.

**Events.** Each carries `config_entry_id`, `zone`, `client`, `domain`, `request_id`
(empty when there is no request) and `actions` (the buttons the request allows).

- `ha_blocky_new_domain`: a request was created.
- `ha_blocky_unexpected_domain`: a locked client asked for a blocked domain.
- `ha_blocky_zone_leak`: see below.
- `ha_blocky_new_domains_summary`: carries only `config_entry_id`, `zone`, `client` and
  `suppressed`.

**Flood limit.** At most 5 of the three per-domain events are fired per client in 10
minutes. After that the events are held back, requests are still created, and one
`ha_blocky_new_domains_summary` per client reports how many were held back.

**Zone leaks.** In an `allowlist_only` zone, a query that Blocky answered (resolved or
cached) for a domain that is on none of the zone's allow lists fires
`ha_blocky_zone_leak` (once per client and domain until it clears) and turns on the
"Zone leak" problem sensor for an hour. The sensor shows only a count, never a client or
a domain. Limits: only the manual lists held by this integration are known; allow
lists that Blocky gets from elsewhere are invisible, so such answers can show up as
false leaks. A list entry covers its own domain and its subdomains, and a wildcard
entry `*.example.com` covers subdomains only; this matching has not been verified
against Blocky's own.

**Baseline.** In the options (New domain requests) you choose what happens with domains
a client asked for before it was tracked. By default (silent baseline) a client first
seen in a `learning` zone has its distinct domains of the last 7 days (up to the
known-pairs cap) taken as known, without events or requests; at most 10 clients are
processed per round, and rows of the others are taken as known silently meanwhile. With
"Report existing history as new" there is no baseline. The baseline does not apply to
`allowlist_only` zones.

**Card.** The query log card has a Requests tab: the pending requests with the buttons
each allows, and the phase of the clients of allowlist-only zones with a switch. Clients
are shown with their name (see "Client names" below).

**Entities.** One sensor with the number of pending requests and one problem sensor for
leaks. Diagnostics contain counts only.

### Notifications

The contract of the integration is the events plus the actions above; it sends no
notification itself. The blueprint
`blueprints/automation/ha_blocky/telegram_requests.yaml` is one example: it sends each
request to a Telegram chat with inline buttons, handles the button presses (only from the
Telegram user ids you list, only the three known commands, only a well-formed request id)
and sends alarms to another chat. Copy it into `config/blueprints/automation/ha_blocky/`.
Its messages are plain text, since domains come from the DNS log.

Any other notification service works the same way. A recipe: trigger on
`ha_blocky_new_domain`; send a message with the zone, client and domain, plus one action
per entry of `actions` (for a mobile app actionable notification, an action whose id
contains the request id); trigger on the response (for the mobile app, the
`mobile_app_notification_action` event); check that the responder is allowed and that the
request id is well formed; then call `ha_blocky.approve_request`,
`ha_blocky.reject_request` or `ha_blocky.block_request` with that request id. Treat the
domain and client as untrusted text and never render them as markup.

## Client names

A client is shown by name in the card (the query log and the Requests tab) and its events
carry a `client_name` field next to `client` (`null` when there is no name). The name of
an address is, in this order:

1. A name you typed: click a client in the card, type a name (up to 64 characters, no
   control characters), press Enter to save, Escape to cancel; saving an empty name clears
   it. Only administrators can do this. Up to 512 names are kept, in Home Assistant's own
   storage.
2. The friendly name of a `device_tracker` entity whose `ip` attribute is the address (if
   several match, the entity with the lowest entity id is used).
3. None: the card shows the address.

Every name goes through the same check, so an unusable name from a device tracker counts as
no name. Names are keyed by IP address: if a device gets another address from DHCP, the name
you typed stays with the old address and the device appears unnamed until you name it again
(a reserved address avoids this). Names never appear in diagnostics or logs. The WebSocket
command `ha_blocky/set_client_name` that the card uses to save a name is internal to the
card, not an interface to build on.

## Sidebar panel

Administrators get an HA-Blocky entry in the sidebar that shows the same card full width.
It is on by default; turn it off in the options under "Show in sidebar" (the integration
reloads when you save). The panel is removed when the last HA-Blocky entry is unloaded.
It needs the `frontend` component (a normal Home Assistant installation has it). The card is
also still available for dashboards as before.

## Dashboard cards

The card is `custom:ha-blocky-card` (it is also the sidebar panel). It has three tabs; on a
narrow card they show their icons only.

**Dashboard** (the first tab). A large switch turns blocking off or on (it drives the
integration's blocking switch entity, so turning it off pauses blocking for the usual few
minutes). The period group (Today, 24 h, 7 d, 30 d) and the number of rows of the top
lists (5, 10, 20) are remembered by the browser. Tiles show the queries, blocked, cached
(cache rate = cached divided by cached plus resolved) and the average answer time. The chart
shows queries per hour (Today, 24 h) or per local day (7 d, 30 d), stacked by how Blocky
answered: resolved, cached, local, blocked, other. The top clients, top domains and top
blocked domains have a thin bar split by the same categories; hover or tap a bar or a row for
the exact counts, the time last seen and, for a blocked domain, the most frequent block
reason. The tab reloads every 60 seconds (`auto_refresh` in the card options sets another
time in seconds, at least 10; 0 turns it off) while it is shown, the page is visible and the
dashboard is not being edited. It needs the query log database; without it only the switch
is shown. The WebSocket command `ha_blocky/dashboard` that it uses reads only aggregates
(counts per category, hour or day, client and domain within the chosen period) from the
database and is internal to the card. The server reuses one answer per entry, period and
rows for 30 seconds.

The colours of the query kinds are the custom properties `--hb-color-resolved`,
`--hb-color-cached`, `--hb-color-local`, `--hb-color-blocked` and `--hb-color-other` of the
card (for example set with a card theme or `card-mod`).

The other tabs are the query log and the requests, described below. The overview card is
`custom:ha-blocky-overview-card`; it needs the query log database and an administrator.

```yaml
type: custom:ha-blocky-overview-card
# Optional: title, entry_id, auto_refresh (seconds; default 60, at least 10, 0 = off).
```

It shows the top domains, top blocked domains and top clients of the last 24 hours with
their counts, and the requests waiting for a decision. A top domain has a Block icon and a
top blocked domain an Allow icon (both open the same list picker as the query log). A
request has Approve and Reject icons (allowlist-only zones) or Block and Dismiss icons
(learning zones). A click on a client names it, as in the query log. It replaces the
markdown tables that read the `items` attribute of the three top-list sensors. The
WebSocket command `ha_blocky/overview` that it uses is internal to the card.

In the query log, repeated rows (same client, domain, type and status) are shown as one
line with `×N` and the latest time while "Group repeats" is ticked (it is ticked by
default and not remembered). In a narrow card, such as on a phone, each entry takes two
lines: client and domain, then time, status icon and the action icon.

The Requests tab also lists the known domains of every tracked client (loaded when you
expand a client). For a client of a learning zone each domain has a Block icon that adds it
to the zone's first deny list. For a client of an allowlist-only zone the list is read-only:
its known domains are on an allow list, and removing entries from there is not done by the
card.

### Chart period switcher

A statistics chart with a period switch needs a helper and four cards. Create an
`input_select` helper named "HA-Blocky chart period" (entity id
`input_select.ha_blocky_chart_period`) with the options `24 h`, `Week` and `Month`, then
put this in a dashboard (a vertical stack or a section). The three sensor entity ids are the
integration's resolved, cached and blocked query counters; check them in your installation.

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: input_select.ha_blocky_chart_period
    features:
      - type: select-options
  - type: conditional
    conditions:
      - condition: state
        entity: input_select.ha_blocky_chart_period
        state: "24 h"
    card:
      type: statistics-graph
      title: Queries
      chart_type: bar-stack
      period: hour
      days_to_show: 1
      stat_types: [change]
      entities:
        - sensor.ha_blocky_resolved_queries
        - sensor.ha_blocky_cached_queries
        - sensor.ha_blocky_blocked_queries
  - type: conditional
    conditions:
      - condition: state
        entity: input_select.ha_blocky_chart_period
        state: "Week"
    card:
      type: statistics-graph
      title: Queries
      chart_type: bar-stack
      period: day
      days_to_show: 7
      stat_types: [change]
      entities:
        - sensor.ha_blocky_resolved_queries
        - sensor.ha_blocky_cached_queries
        - sensor.ha_blocky_blocked_queries
  - type: conditional
    conditions:
      - condition: state
        entity: input_select.ha_blocky_chart_period
        state: "Month"
    card:
      type: statistics-graph
      title: Queries
      chart_type: bar-stack
      period: day
      days_to_show: 30
      stat_types: [change]
      entities:
        - sensor.ha_blocky_resolved_queries
        - sensor.ha_blocky_cached_queries
        - sensor.ha_blocky_blocked_queries
```

**Not verified on Home Assistant 2026.10.4:** that the `tile` card offers the
`select-options` feature for an `input_select` there. If it does not, replace the tile with
three `button` cards that set the helper (the key is `perform_action` in current Home
Assistant; older versions call it `service`):

```yaml
type: horizontal-stack
cards:
  - type: button
    name: 24 h
    tap_action:
      action: perform-action
      perform_action: input_select.select_option
      target:
        entity_id: input_select.ha_blocky_chart_period
      data:
        option: "24 h"
  - type: button
    name: Week
    tap_action:
      action: perform-action
      perform_action: input_select.select_option
      target:
        entity_id: input_select.ha_blocky_chart_period
      data:
        option: "Week"
  - type: button
    name: Month
    tap_action:
      action: perform-action
      perform_action: input_select.select_option
      target:
        entity_id: input_select.ha_blocky_chart_period
      data:
        option: "Month"
```

## Requirements

- Home Assistant 2026.10 or newer.
- Blocky v0.35.0 or newer, reachable from Home Assistant over HTTP.
- Optional: Blocky's query log written to a MySQL/MariaDB database, for the
  query log, statistics and approval workflow.

## Security note

Blocky's HTTP API has no authentication. Do not expose the Blocky HTTP port
outside a trusted network segment.

## License

[Apache License 2.0](LICENSE)
