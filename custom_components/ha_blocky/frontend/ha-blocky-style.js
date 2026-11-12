/* Styles of the HA-Blocky card (plain text, no data is ever added to them). */

import { DASHBOARD_STYLE } from "./ha-blocky-style-dashboard.js";

export const STYLE = `
  :host {
    display: block;
    /* The colour of each kind of query; change them to restyle every bar,
       tile, legend and badge at once. */
    --hb-color-resolved: #26a69a;
    --hb-color-cached: #42a5f5;
    --hb-color-local: #ab47bc;
    --hb-color-blocked: #ef5350;
    --hb-color-other: #9e9e9e;
    /* The colour of the effect of an action: lets through / keeps out. */
    --hb-good: var(--success-color, #43a047);
    --hb-bad: var(--error-color, #db4437);
  }
  .body { padding: 0 16px 16px; container-type: inline-size; }
  .filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .filters input, .filters select, .panel select {
    flex: 1 1 140px; min-width: 0; box-sizing: border-box; padding: 8px;
    font: inherit; color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: 6px;
  }
  button {
    font: inherit; cursor: pointer; padding: 6px 12px; border-radius: 6px;
    color: var(--primary-text-color); background: transparent;
    border: 1px solid var(--divider-color);
  }
  button.primary {
    color: var(--text-primary-color); background: var(--primary-color);
    border-color: var(--primary-color);
  }
  button:disabled { opacity: 0.5; cursor: default; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  th, td {
    text-align: left; padding: 6px 8px; white-space: nowrap;
    border-bottom: 1px solid var(--divider-color);
  }
  th { cursor: pointer; user-select: none; color: var(--secondary-text-color); }
  th.plain { cursor: default; }
  td.domain {
    white-space: normal; word-break: break-all;
    font-family: var(--code-font-family, monospace);
  }
  td.num, th.num { text-align: right; }
  tr.blocked td.status { color: var(--error-color); font-weight: 500; }
  td.actions button { padding: 2px 8px; margin-right: 4px; font-size: 0.9em; }
  .panel {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
    margin: 12px 0; padding: 12px; border-radius: 6px;
    border: 1px solid var(--primary-color);
  }
  .panel .name {
    word-break: break-all; font-family: var(--code-font-family, monospace);
  }
  .zone { font-size: 0.85em; color: var(--secondary-text-color); }
  .message { margin: 12px 0; color: var(--secondary-text-color); }
  .message.error { color: var(--error-color); }
  .footer {
    display: flex; align-items: center; justify-content: space-between;
    gap: 8px; margin-top: 12px; color: var(--secondary-text-color);
  }
  .tabs { display: flex; gap: 8px; margin: 0 0 12px; }
  button.tab {
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    min-height: 40px;
  }
  ha-icon.tabicon { display: inline-flex; --mdc-icon-size: 20px; }
  button.tab.active {
    color: var(--text-primary-color); background: var(--primary-color);
    border-color: var(--primary-color);
  }
  .sub { color: var(--secondary-text-color); font-size: 0.85em; }
  h3 { margin: 16px 0 8px; font-size: 1em; font-weight: 500; }
  td.buttons button { margin-right: 4px; }
  .rowerror { color: var(--error-color); font-size: 0.85em; white-space: normal; }
  td.client { cursor: pointer; }
  td.client:focus-visible { outline: 2px solid var(--primary-color); }
  .main { font-weight: 500; }
  input.nameedit {
    box-sizing: border-box; width: 100%; min-width: 140px; padding: 4px 6px;
    font: inherit; color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--primary-color); border-radius: 6px;
  }
  label.check {
    display: flex; align-items: center; gap: 6px; flex: 0 0 auto;
    color: var(--primary-text-color); cursor: pointer;
  }
  span.count { margin-left: 6px; color: var(--secondary-text-color); font-size: 0.85em; }
  .iconbtn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 28px; border-radius: 50%; cursor: pointer;
    color: var(--secondary-text-color); --mdc-icon-size: 20px;
  }
  .iconbtn:hover { background: var(--divider-color); color: var(--primary-text-color); }
  .iconbtn:focus-visible { outline: 2px solid var(--primary-color); }
  /* Icons and buttons take the colour of what they do. */
  .iconbtn.fx-good, .iconbtn.fx-good:hover { color: var(--hb-good); }
  .iconbtn.fx-bad, .iconbtn.fx-bad:hover { color: var(--hb-bad); }
  .iconbtn.fx-good:hover { background: color-mix(in srgb, var(--hb-good) 18%, transparent); }
  .iconbtn.fx-bad:hover { background: color-mix(in srgb, var(--hb-bad) 18%, transparent); }
  button.fx-good { color: var(--hb-good); border-color: var(--hb-good); }
  button.fx-bad { color: var(--hb-bad); border-color: var(--hb-bad); }
  button.fx-good:hover { background: color-mix(in srgb, var(--hb-good) 15%, transparent); }
  button.fx-bad:hover { background: color-mix(in srgb, var(--hb-bad) 15%, transparent); }
  /* The row an action was done on lights up and fades out. */
  tr, .knownrow { transition: background-color 0.9s ease-out; }
  tr.flash-good, .knownrow.flash-good {
    background-color: color-mix(in srgb, var(--hb-good) 28%, transparent);
  }
  tr.flash-bad, .knownrow.flash-bad {
    background-color: color-mix(in srgb, var(--hb-bad) 28%, transparent);
  }
  @media (prefers-reduced-motion: reduce) {
    tr, .knownrow { transition: none; }
  }
  .iconbtn[aria-disabled="true"] { opacity: 0.4; cursor: default; }
  td.actions, td.buttons { white-space: nowrap; }
  ha-icon.statusicon { display: none; --mdc-icon-size: 18px; }
  .lists {
    display: grid; gap: 0 16px;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  }
  .lists .section, .section { min-width: 0; }
  .known { padding: 4px 0 8px; }
  .knownrow { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .knownrow .domain {
    word-break: break-all; font-family: var(--code-font-family, monospace);
  }
  /* Narrow card (a phone, or a narrow column): two lines per log entry.
     Line 1: client and domain. Line 2: time, status icon, action icon. */
  @container (max-width: 560px) {
    table.log thead { display: none; }
    table.log, table.log tbody { display: block; }
    table.log tr {
      display: grid; grid-template-columns: auto minmax(0, 1fr) auto;
      grid-template-areas: "client domain domain" "time status actions";
      align-items: center; gap: 2px 12px; padding: 6px 0;
      border-bottom: 1px solid var(--divider-color);
    }
    table.log td { display: block; border: 0; padding: 0; white-space: normal; }
    table.log td.client { grid-area: client; }
    table.log td.domain { grid-area: domain; }
    table.log td.time { grid-area: time; color: var(--secondary-text-color); }
    table.log td.status { grid-area: status; }
    table.log td.actions { grid-area: actions; text-align: right; }
    table.log td.type, table.log td.ms { display: none; }
    table.log td.client .sub { display: none; }
    table.log td.status .statustext { display: none; }
    table.log td.status ha-icon.statusicon { display: inline-flex; }
    .scroll { overflow-x: visible; }
    /* The requests: client, domain, then zone and age, then the buttons. */
    table.req thead { display: none; }
    table.req, table.req tbody { display: block; }
    table.req tr {
      display: grid; grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas: "client client" "domain domain" "zone age" "buttons buttons";
      align-items: center; gap: 2px 12px; padding: 8px 0;
      border-bottom: 1px solid var(--divider-color);
    }
    table.req td { display: block; border: 0; padding: 0; white-space: normal; }
    table.req td.client { grid-area: client; }
    table.req td.domain { grid-area: domain; }
    table.req td.zone { grid-area: zone; color: var(--secondary-text-color); }
    table.req td.age { grid-area: age; color: var(--secondary-text-color); }
    table.req td.buttons { grid-area: buttons; padding-top: 4px; }
    table.req td.buttons button { min-height: 36px; }
    /* The known domains: the client above its button, the list below. */
    table.kn, table.kn tbody { display: block; }
    table.kn tr { display: grid; grid-template-columns: minmax(0, 1fr); gap: 4px; padding: 6px 0; }
    table.kn td { display: block; border: 0; padding: 0; white-space: normal; }
  }
  ${DASHBOARD_STYLE}
  @container (max-width: 560px) {
    .tablabel { display: none; }
    button.tab { flex: 1 1 0; }
  }
  [hidden] { display: none !important; }
`;
