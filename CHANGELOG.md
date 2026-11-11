# Changelog

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
