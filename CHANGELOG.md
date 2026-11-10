# Changelog

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
