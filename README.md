# HA-Blocky

A Home Assistant custom integration for the [Blocky](https://github.com/0xERR0R/blocky)
DNS proxy and ad-blocker.

> **Status: early development.** The integration can pause and resume blocking,
> refresh lists, flush the cache, report whether Blocky is reachable, show
> statistics from Blocky's query log database, give each client one of four
> protection levels, manage the rules of those levels, see a dashboard and browse
> the query log in a card or a sidebar panel, name clients and handle requests
> for new domains.

## Goals

- Control Blocky from Home Assistant: enable or pause blocking, refresh lists,
  flush the cache.
- Show what the DNS filter is doing: query counters, blocked ratio, top domains
  and clients, and a searchable query log read from Blocky's database log.
- Give each client (device) one of four protection levels and manage the rules of
  those levels from Home Assistant.
- Support a Lockdown level with an approval workflow, so a new device can only reach
  domains that were explicitly approved.
- Expose events and actions so approvals can be driven from automations.

## Comparison

How Blocky with HA-Blocky compares with two well-known DNS filters. The Blocky column
describes Blocky v0.35 itself plus what this integration adds on top of it. Cells marked
"not documented" mean the feature is not mentioned in Blocky's documentation; check the
current documentation of each project before relying on this table.

| Feature | AdGuard Home | Pi-hole | Blocky + HA-Blocky |
|---|---|---|---|
| Blocking ads and trackers | ✅ | ✅ | 🟡 Through lists that you add to Blocky's configuration |
| Customizing blocklists | ✅ | ✅ | ✅ Blocky list groups, plus four rule lists (Always allow, Always block, Restricted block list, Lockdown allow list) managed from Home Assistant |
| Built-in DHCP server | ✅ | ✅ | ❌ |
| HTTPS for the admin interface | ✅ | ✅ | ➖ No admin interface of its own: the card lives inside Home Assistant (administrators only). Blocky's HTTP API has no authentication |
| Encrypted DNS upstream servers | ✅ DoH, DoT, DNSCrypt | ❌ Requires additional software | ✅ DoH and DoT (DNSCrypt not documented) |
| Cross-platform | ✅ | ❌ Not natively, only via Docker | ✅ Single Go binary or container; the integration needs Home Assistant 2026.10 or newer |
| Running as a DoH or DoT server | ✅ | ❌ Requires additional software | ✅ |
| Blocking phishing and malware domains | ✅ | 🟡 Requires non-default blocklists | 🟡 Add a malware or phishing list, same as for ads |
| Parental control (blocking adult domains) | ✅ | 🟡 Requires non-default blocklists | 🟡 Add an adult-content list to the client group that needs it |
| Force safe search on search engines | ✅ | ❌ | Not documented |
| Per-client (device) configuration | ✅ | ✅ | ✅ Client groups in Blocky; four protection levels (Unfiltered, Standard, Restricted, Lockdown) chosen per device in the card |
| Access settings (who can use the DNS) | ✅ | ❌ | Not documented |
| Approval workflow for new domains | ❌ | ❌ | ✅ Requests with Approve, Reject and Block |
| Lockdown level with leak detection | ❌ | ❌ | ✅ |
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

Leak detection (see above) is related but different: it reports answers Blocky gave
to a Lockdown client for domains that are not on the Lockdown allow list.

## Design principles

- **Zero trust.** Every input is treated as hostile, including domain names read
  from the DNS query log, API responses and database rows.
- **Least privilege.** The integration only needs read access to the query log
  database. Actions and data access are limited to Home Assistant administrators.
- **Fail closed.** A failure of the integration must never disable filtering or
  open a Lockdown client.
- **Minimal dependencies.** No frontend build step and no third-party frontend
  packages.
- **Nothing network-specific in the code.** Clients, levels and rules are
  configured by the user.

## Clients and protection levels

Every client (one IP address, IPv4 or IPv6) has one of four levels. Standard is the
default and is the absence of a setting. You choose a level per device in the Settings
tab of the card, under "Clients and levels"; the card lists every device seen in the query
log in the last 7 days. At most 64 clients can have a level.

| | Unfiltered | Standard | Restricted | Lockdown |
|---|---|---|---|---|
| **What is blocked** | Nothing. | Ads, trackers and malware from your block lists, plus Always block. | Like Standard, plus the Restricted block list. | Everything except the domains on the Lockdown allow list. |
| **Whose rules apply** | None. Even Always block is ignored. | The shared Always allow and Always block rules. | Standard's rules, plus the Restricted block list shared by every Restricted client. | Only the Lockdown allow list, shared by every Lockdown client. Standard's rules do not apply. |
| **Asked and notified** | Nothing. The queries are still logged. | Nothing. | Each new domain becomes a request you can Block or Dismiss. Notifications are Off at first. | With "Ask me about new domains" on, each blocked new domain becomes a request. Notifications are On at first. |
| **A new domain** | Works. | Works, unless a list blocks it. | Works. It is listed for review; nothing is held back. | Blocked until you approve it. Approving opens it for every Lockdown client. |

Allowing or blocking a domain applies to every client of the level; what is tracked as
"new" stays per client.

**Which level for what**

- A site is broken and you wonder whether the filter is the cause: set that device to
  **Unfiltered** for a while. If the problem goes away, filtering was the cause; put the
  device back to Standard.
- Family phones and computers: **Standard**. Nothing to do.
- A child's device: **Restricted**. It gets an extra block list, and every new domain it
  visits is listed for review. Nothing is held back.
- An IoT device, a robot vacuum or a smart TV that should only reach its vendor:
  **Lockdown**. Keep "Ask me about new domains" on while it is learning, and turn it off
  once it works reliably (a blocked new domain is then only reported as an unexpected
  domain).

**Rules.** Four fixed lists, edited in the card (Settings, "Rules") or with the actions
`allow_domain`, `block_domain` and `remove_domain`: `allow_default` (Always allow) and
`deny_default` (Always block) are the shared rules of Standard and Restricted;
`restricted_deny` is the Restricted block list; `lockdown_allow` is the Lockdown allow
list (exact domains only: a wildcard entry is refused when you add it). An entry covers
its own domain and its subdomains; `*.example.com` covers subdomains only. Blocky is asked
to reload its lists a few seconds after a change.

**How a change gets applied.** Home Assistant never writes Blocky's configuration, so a
change of levels needs these steps:

1. Change a device's level. A banner shows "N changes waiting".
2. Press "Show block to paste", then "Copy block". The block lists the list groups and one
   client line per device that is not at Standard, in the format of the Blocky app
   (Configuration tab) and in Blocky's own YAML for Docker or Custom Config Mode.
3. Paste it into Blocky's configuration: add these entries, do not replace the whole option.
4. Restart Blocky.
5. Press "Check now". It asks Blocky to refresh its lists and reads the status again.
6. The banner changes to "Applied".

The block contains the secret list addresses, so it is shown to administrators only. Every
list address carries `?r=<rev>`, where `rev` is the first 8 hex characters of the SHA-256 of
the base list groups and the sorted client lines; it is not secret. The list endpoint serves
the same content whatever `r` is and only remembers (in memory) which `rev` Blocky fetched
last for each of the fixed lists, and only when `r` is exactly 8 lower-case hex characters
and the request is entitled to the list. The status is "applied" when Blocky fetched every
list with the current `rev`. After a Home Assistant restart it says that it is waiting until
Blocky fetches the lists again.

**Standard list groups.** In Blocky a client line lists *list groups* (the keys of
`denylists` and `allowlists`), not other client groups, and a client with its own line does
not inherit the `default` client group. So the card asks which list groups your `default`
client group uses (the option `base_groups`, 1 to 16 names, default `default`). A
Restricted client gets these plus `restricted`; Unfiltered gets `unfiltered`; Lockdown gets
`lockdown`; Standard has no line. Changing the base groups changes the `rev`, so the change
is waiting until you paste the new block.

**Not yet verified live.** These four points are marked as unverified in the code and the
tests until they have been checked on a real Blocky: (a) Blocky fetches the lists again
after a restart and keeps the query string, so "Check now" flips the status to applied;
(b) a Restricted client still resolves an ordinary domain (Restricted did not become
allowlist-only); (c) an Unfiltered client resolves a domain that is on `deny_default` (an
empty group is accepted); (d) a Lockdown client is blocked on an unknown domain and Approve
opens it (a cached block answer can last up to the 5 minute block TTL).

**Setup check.** A read-only panel in the Settings tab: Blocky API reachable, query log
readable, per level whether Blocky has fetched its list, and whether Blocky has the current
settings.

**Sensors.** The 24 hour query and blocked-query counters exist per level for Unfiltered,
Restricted and Lockdown (none for Standard).

**Upgrading from 0.12.** The old network groups and free lists are migrated once when the integration loads
(see the changelog of 0.13.0): a learning group of single hosts becomes Restricted clients, an
allowlist-only group of single hosts becomes Lockdown clients (the entries of its linked allow
lists are copied to the Lockdown allow list), and a group with a wider network or in filter
mode is dropped with a log line that carries only a count and a reason code.

## New-domain tracking

With the query log database configured, the integration watches the clients at the
Restricted and Lockdown levels and turns what they ask for into events and requests.
Nothing is tracked for the other levels or for clients without a level.

- **Restricted** client: the first time it asks for a domain, the integration creates a
  request with the actions Block and Dismiss and (if the notification of the level is
  not Off) fires `ha_blocky_new_domain`. Block adds the exact domain to the Restricted
  block list. Dismiss only closes the request. Either way the pair of client and domain
  is known from then on. Nothing is held back.
- **Lockdown** client with "Ask me about new domains" on: a new domain whose answer was
  blocked creates a request with the actions Approve and Reject and fires
  `ha_blocky_new_domain`. Approve adds the exact domain to the Lockdown allow list.
  Reject remembers the pair, which then never raises a request again. With the switch
  off, a new blocked domain raises no request and fires `ha_blocky_unexpected_domain`,
  once per pair. The switch is the `ask` of the client; change it in the card or with the
  action `ha_blocky.set_client_ask`.

**Notifications.** Per level (Restricted, Lockdown) the card has Off or Each. Off fires no
`ha_blocky_new_domain`, `ha_blocky_unexpected_domain` or summary event for that level
(requests are still created and shown in the Requests tab). Leaks are always reported. The
defaults are Off for Restricted and Each for Lockdown.

**Life cycle of a request.** A request has a random id, is single use and expires
after 24 hours. When a Restricted request expires, the pair is treated as known; for a
Lockdown client it is not, so the next blocked query raises a new request. At most 200
requests are pending; beyond that no new request is created. Per client at most 1000 known
and 500 rejected pairs are kept (the least recently seen are forgotten first), and at most
256 clients are tracked. Changing a client's level starts its tracking afresh.

**Actions** (administrators only)

- `ha_blocky.approve_request`: `request_id`.
- `ha_blocky.reject_request`: `request_id` (for a Restricted client this is Dismiss).
- `ha_blocky.block_request`: `request_id`, Restricted clients only.
- `ha_blocky.get_requests`: returns the pending requests.
- `ha_blocky.set_client_ask`: `client` (IP address of a Lockdown client), `ask` (true or false).
- `ha_blocky.allow_domain`, `block_domain`, `remove_domain` and `get_list`: `list` is one of
  `allow_default`, `deny_default`, `restricted_deny`, `lockdown_allow`.

All of them accept an optional `config_entry_id` when more than one Blocky instance is
set up.

**Events.** Each carries `config_entry_id`, `level`, `client`, `domain`, `request_id`
(empty when there is no request) and `actions` (the buttons the request allows).

- `ha_blocky_new_domain`: a request was created.
- `ha_blocky_unexpected_domain`: a Lockdown client without "Ask me about new domains"
  asked for a blocked domain.
- `ha_blocky_lockdown_leak`: see below.
- `ha_blocky_new_domains_summary`: carries only `config_entry_id`, `level`, `client` and
  `suppressed`.

**Flood limit.** At most 5 of the three per-domain events are fired per client in 10
minutes. After that the events are held back, requests are still created, and one
`ha_blocky_new_domains_summary` per client reports how many were held back.

**Leaks.** For a Lockdown client, a query that Blocky answered (resolved or cached) for a
domain that is not on the Lockdown allow list fires `ha_blocky_lockdown_leak` (once per
client and domain until it clears) and turns on the "Lockdown leak" problem sensor for an
hour. The sensor shows only a count, never a client or a domain. Limits: only the
list held by this integration is known; allow lists that Blocky gets from elsewhere are
invisible, so such answers can show up as false leaks. A list entry covers its own domain
and its subdomains; this matching has not been verified against Blocky's own.

**Baseline.** In the Settings tab of the card ("Report existing history as new") you choose what happens with domains
a client asked for before it was tracked. By default (silent baseline) a Restricted client first
seen has its distinct domains of the last 7 days (up to the
known-pairs cap) taken as known, without events or requests; at most 10 clients are
processed per round, and rows of the others are taken as known silently meanwhile. With
"Report existing history as new" there is no baseline. The baseline does not apply to
Lockdown clients.

**Card.** The query log card has a Requests tab: the pending requests with the buttons
each allows, and the known domains of every tracked client. Clients are shown with their
name (see "Client names" below).

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
`ha_blocky_new_domain`; send a message with the level, client and domain, plus one action
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
It is on by default; turn it off in the Settings tab of the card under "Show in sidebar" (the integration
reloads when you save). The panel is removed when the last HA-Blocky entry is unloaded.
It needs the `frontend` component (a normal Home Assistant installation has it). The card is
also still available for dashboards as before.

## Dashboard cards

The card is `custom:ha-blocky-card` (it is also the sidebar panel). It has five tabs (Dashboard, Query log, Requests, Settings, Help); on a
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

**Settings.** Two kinds of settings, both written through the administrator-only command
`ha_blocky/set_settings` (read with `ha_blocky/settings`; both are internal to the card).
*Display* (kept by Home Assistant, applied at once, nothing reloads): the colour of each kind
of query (resolved, cached, local, blocked, other; a colour is exactly `#rrggbb`, and the
card applies them through one style element) and the default number of rows of the
dashboard top lists (5, 10, 20; a choice made on the dashboard in a browser wins over it in
that browser). *Operation* (options of the integration; saving them reloads it): the three
update intervals (blocking status, query counters, top lists), "Report existing history as
new" and "Show in sidebar" (off removes the sidebar entry; the card stays usable from a
dashboard). The Configure menu of the integration keeps only the database and the clients
that may download lists; the list addresses are inside the block.

*Protection* comes first in the tab and has its own administrator-only commands
(`ha_blocky/levels`, `set_client_level`, `set_base_groups`, `set_notify`, `get_block`,
`rules`, `rules_add`, `rules_remove`; all internal to the card): the clients with a level
dropdown and, for Lockdown, "Ask me about new domains"; notifications Off or Each for
Restricted and Lockdown; the Standard list groups; the Rules; "Applying changes to Blocky"
with the block, the copy button and "Check now"; and the setup check. Every control has a
short hint.

**Live mode.** The Live button of the Query log tab reads the first page of the log every 3
seconds, only while the page is visible, for at most 10 minutes; it stops when you leave the
tab. Rows that are new since the previous read light up briefly. Blocky writes its log in
batches, so entries can appear with a delay.

**Help.** A short quick start, a comparison of the four levels with use cases and the
steps of applying a change, a few answers, and three well-known blocklist sources
(StevenBlack hosts, HaGeZi Pro, OISD big) as plain text with a copy button. They are not
links and the card never fetches them. List sources are added in Blocky's own
configuration; HA-Blocky does not apply them.

The other tabs are the query log and the requests, described below. The overview card is
`custom:ha-blocky-overview-card`; it needs the query log database and an administrator.

```yaml
type: custom:ha-blocky-overview-card
# Optional: title, entry_id, auto_refresh (seconds; default 60, at least 10, 0 = off).
```

It shows the top domains, top blocked domains and top clients of the last 24 hours with
their counts, and the requests waiting for a decision. A top domain has a Block icon and a
top blocked domain an Allow icon (both open the same list picker as the query log). A
request has Approve and Reject icons (Lockdown clients) or Block and Dismiss icons
(Restricted clients). A click on a client names it, as in the query log. It replaces the
markdown tables that read the `items` attribute of the three top-list sensors. The
WebSocket command `ha_blocky/overview` that it uses is internal to the card.

In the query log, repeated rows (same client, domain, type and status) are shown as one
line with `×N` and the latest time while "Group repeats" is ticked (it is ticked by
default and not remembered). In a narrow card, such as on a phone, each entry takes two
lines: client and domain, then time, status icon and the action icon.

The Requests tab also lists the known domains of every tracked client (loaded when you
expand a client). For a Restricted client each domain has a Block icon that adds it to the
Restricted block list. For a Lockdown client the list is read-only: its known domains are on
the Lockdown allow list, which you edit under Rules in the Settings tab.

## FAQ

**A site is broken. Is it the filter?** Set the device to Unfiltered for a while (Settings,
Clients and levels). If it works then, filtering was the cause; look in the query log for
the blocked domain and allow it, then set the device back to Standard.

**The banner says "N changes waiting".** Blocky has not fetched the lists with the current
settings yet. Copy the block, paste it into Blocky (add, do not replace), restart Blocky and
press "Check now". After a Home Assistant restart it can also say waiting until Blocky
fetches the lists again.

**"Check now" does not turn the banner to Applied.** Blocky must fetch the three list
addresses of the block with the `?r=` part kept. If it does not (point (a) above is not yet
verified live), tell the maintainer; a per-revision file name is the fallback.

**Which names go into "Standard list groups"?** The list groups your Blocky `default`
client group uses, for example `default`. Restricted clients get these plus the Restricted
block list, because a Blocky client with its own line does not inherit the `default` group.

**A Lockdown device does not work at all.** That is the level: only approved domains work.
Keep "Ask me about new domains" on, use the device, then approve what it needs in the
Requests tab (or add the domains under Rules). Turn the switch off once it is stable.

**The device got another address.** Levels and names are kept per IP address. A reserved
address (DHCP reservation) avoids this.

**Where did the old network groups and free lists go?** They were replaced by the four levels in 0.13.0 and
migrated once; see the changelog.

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
