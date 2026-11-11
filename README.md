# HA-Blocky

A Home Assistant custom integration for the [Blocky](https://github.com/0xERR0R/blocky)
DNS proxy and ad-blocker.

> **Status: early development.** The integration can pause and resume blocking,
> refresh lists, flush the cache, report whether Blocky is reachable, show
> statistics from Blocky's query log database, manage manual allow and deny
> lists, browse the query log in a dashboard card and handle requests for new
> domains.

## Goals

- Control Blocky from Home Assistant: enable or pause blocking, refresh lists,
  flush the cache.
- Show what the DNS filter is doing: query counters, blocked ratio, top domains
  and clients, and a searchable query log read from Blocky's database log.
- Manage manual allow and deny lists from Home Assistant, per client group.
- Support allowlist-only client groups with an approval workflow, so a new
  device can only reach domains that were explicitly approved.
- Expose events and actions so approvals can be driven from automations.

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
each allows, and the phase of the clients of allowlist-only zones with a switch. A
device name is shown when a `device_tracker` entity has the client's address in its
`ip` attribute.

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
