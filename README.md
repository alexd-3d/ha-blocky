# HA-Blocky

A Home Assistant custom integration for the [Blocky](https://github.com/0xERR0R/blocky)
DNS proxy and ad-blocker.

> **Status: early development.** The integration can pause and resume blocking,
> refresh lists, flush the cache and report whether Blocky is reachable. The
> query log, statistics and list management are not implemented yet.

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
