/* Styles of the HA-Blocky card (plain text, no data is ever added to them). */

import { DASHBOARD_STYLE } from "./ha-blocky-style-dashboard.js";
import { CATEGORIES, DEFAULT_COLORS } from "./ha-blocky-format.js";
import { MORE_STYLE } from "./ha-blocky-style-more.js";
import { TABS_STYLE } from "./ha-blocky-style-tabs.js";

// The defaults of the category colours; a saved colour overrides them.
const DEFAULT_VARS = CATEGORIES.map((kind) => `--hb-color-${kind}: ${DEFAULT_COLORS[kind]};`).join(" ");

export const STYLE = `
  :host {
    display: block;
    /* The colour of each kind of query; change them to restyle every bar,
       tile, legend and badge at once. */
    ${DEFAULT_VARS}
    /* The colour of the effect of an action: lets through / keeps out. */
    --hb-good: var(--success-color, #43a047);
    --hb-bad: var(--error-color, #db4437);
    /* Spacing on a 4/8 px grid. */
    --hb-s1: 4px; --hb-s2: 8px; --hb-s3: 12px; --hb-s4: 16px; --hb-s6: 24px;
    /* Type scale: title, body, label; the big number of a tile. */
    --hb-fs-title: 16px; --hb-fs-body: 14px; --hb-fs-label: 12px; --hb-fs-value: 28px;
    --hb-fw-medium: 500;
    /* Shapes: controls, cards inside the card, pills. */
    --hb-radius-s: 8px;
    --hb-radius-m: min(var(--ha-card-border-radius, 12px), 16px);
    --hb-radius-pill: 999px;
    /* Height of a control (a touch target on a narrow card), and the look of
       a hover and of a quiet surface. */
    --hb-control: 36px;
    --hb-outline: var(--outline-color, var(--divider-color));
    --hb-hover: color-mix(in srgb, var(--primary-text-color) 8%, transparent);
    --hb-surface: color-mix(in srgb, var(--primary-text-color) 5%, transparent);
    --hb-tonal: color-mix(in srgb, var(--primary-color) 14%, transparent);
  }
  .body {
    padding: 0 var(--hb-s4) var(--hb-s4); container-type: inline-size;
    font-size: var(--hb-fs-body); line-height: 20px; color: var(--primary-text-color);
  }

  /* Fields: one look for every input, select and text area. */
  input[type="text"], input[type="search"], input[type="number"], select, textarea {
    box-sizing: border-box; min-height: var(--hb-control); min-width: 0;
    padding: 0 var(--hb-s3); font: inherit; color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--hb-outline); border-radius: var(--hb-radius-s);
  }
  textarea { padding: var(--hb-s2) var(--hb-s3); }
  input:focus-visible, select:focus-visible, textarea:focus-visible {
    outline: 2px solid var(--primary-color); outline-offset: -1px;
    border-color: var(--primary-color);
  }
  .filters { display: flex; flex-wrap: wrap; align-items: center; gap: var(--hb-s2); margin-bottom: var(--hb-s3); }
  .filters input, .filters select, .panel select { flex: 1 1 140px; }

  /* Action buttons: outlined, with a hover and a focus state. A badge is a
     different thing (see .badge): it does nothing. */
  button {
    font: inherit; font-weight: var(--hb-fw-medium); cursor: pointer;
    min-height: var(--hb-control); padding: 0 var(--hb-s4); border-radius: var(--hb-radius-s);
    color: var(--primary-color); background: transparent;
    border: 1px solid var(--hb-outline);
  }
  button:hover:not(:disabled) { background: color-mix(in srgb, var(--primary-color) 8%, transparent); }
  button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  button.primary {
    color: var(--text-primary-color); background: var(--primary-color);
    border-color: var(--primary-color);
  }
  button.primary:hover:not(:disabled) {
    background: color-mix(in srgb, var(--primary-color) 88%, var(--primary-text-color));
  }
  button:disabled { opacity: 0.5; cursor: default; }
  button.abtn { padding: 0 var(--hb-s3); }

  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td {
    text-align: left; padding: var(--hb-s2) var(--hb-s3); white-space: nowrap;
    border-bottom: 1px solid var(--divider-color);
  }
  th:first-child, td:first-child { padding-left: 0; }
  th:last-child, td:last-child { padding-right: 0; }
  th {
    cursor: pointer; user-select: none; color: var(--secondary-text-color);
    font-size: var(--hb-fs-label); font-weight: var(--hb-fw-medium);
  }
  th.plain { cursor: default; }
  /* Long values (a domain, a level, a client) are cut with an ellipsis; the
     whole text is the title of the cell. */
  td.domain {
    width: 100%; max-width: 0; overflow: hidden; text-overflow: ellipsis;
    font-family: var(--code-font-family, monospace);
  }
  td.level { max-width: 12rem; overflow: hidden; text-overflow: ellipsis; }
  td.client { max-width: 10rem; }
  /* Only for screen readers: the header of a column of icons. */
  th.vh { width: 1px; padding: 0; overflow: hidden; font-size: 0; }
  .main, .sub { min-width: 0; }
  td.client .main, td.client .sub { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.num, th.num { text-align: right; }
  td.time .count {
    margin-left: var(--hb-s2); color: var(--secondary-text-color); font-size: var(--hb-fs-label);
  }
  td.actions button { margin-right: var(--hb-s1); }
  .panel {
    display: flex; flex-wrap: wrap; align-items: center; gap: var(--hb-s2) var(--hb-s3);
    margin: var(--hb-s3) 0; padding: var(--hb-s3) var(--hb-s4); border-radius: var(--hb-radius-m);
    background: var(--hb-tonal);
  }
  .panel .name {
    word-break: break-all; font-family: var(--code-font-family, monospace);
  }
  .panel .plabel, .panel .presult { color: var(--secondary-text-color); }
  .level { font-size: var(--hb-fs-label); color: var(--secondary-text-color); }
  .message { margin: var(--hb-s3) 0; color: var(--secondary-text-color); }
  .message.error { color: var(--error-color); }
  .footer {
    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
    gap: var(--hb-s2); margin-top: var(--hb-s3); color: var(--secondary-text-color);
    font-size: var(--hb-fs-label);
  }
  .tabs { display: flex; gap: var(--hb-s2); margin: 0 0 var(--hb-s4); }
  button.tab {
    display: inline-flex; align-items: center; justify-content: center; gap: var(--hb-s2);
    min-height: 40px; border-color: transparent; color: var(--secondary-text-color);
    border-radius: var(--hb-radius-pill);
  }
  ha-icon.tabicon { display: inline-flex; --mdc-icon-size: 20px; }
  button.tab:hover:not(:disabled) { background: var(--hb-hover); }
  button.tab.active {
    color: var(--primary-text-color); background: var(--hb-tonal);
    border-color: transparent;
  }
  .sub { color: var(--secondary-text-color); font-size: var(--hb-fs-label); }
  h3 { margin: var(--hb-s4) 0 var(--hb-s2); font-size: var(--hb-fs-title); font-weight: var(--hb-fw-medium); }
  td.buttons button { margin-right: var(--hb-s2); }
  .rowerror { color: var(--error-color); font-size: var(--hb-fs-label); white-space: normal; }
  td.client { cursor: pointer; }
  td.client:focus-visible { outline: 2px solid var(--primary-color); }
  .main { font-weight: var(--hb-fw-medium); }
  input.nameedit { width: 100%; min-width: 140px; border-color: var(--primary-color); }
  label.check {
    display: flex; align-items: center; gap: var(--hb-s2); flex: 0 0 auto;
    min-height: var(--hb-control); color: var(--primary-text-color); cursor: pointer;
  }
  span.count { color: var(--secondary-text-color); font-size: var(--hb-fs-label); }
  .iconbtn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 32px; height: 32px; border-radius: 50%; cursor: pointer;
    color: var(--secondary-text-color); --mdc-icon-size: 20px;
  }
  .iconbtn:hover { background: var(--divider-color); color: var(--primary-text-color); }
  .iconbtn:focus-visible { outline: 2px solid var(--primary-color); }
  /* Icons and buttons take the colour of what they do. */
  .iconbtn.fx-good, .iconbtn.fx-good:hover { color: var(--hb-good); }
  .iconbtn.fx-bad, .iconbtn.fx-bad:hover { color: var(--hb-bad); }
  .iconbtn.fx-good:hover { background: color-mix(in srgb, var(--hb-good) 18%, transparent); }
  .iconbtn.fx-bad:hover { background: color-mix(in srgb, var(--hb-bad) 18%, transparent); }
  button.fx-good { color: var(--hb-good); border-color: color-mix(in srgb, var(--hb-good) 50%, transparent); }
  button.fx-bad { color: var(--hb-bad); border-color: color-mix(in srgb, var(--hb-bad) 50%, transparent); }
  button.fx-good:hover:not(:disabled) { background: color-mix(in srgb, var(--hb-good) 15%, transparent); }
  button.fx-bad:hover:not(:disabled) { background: color-mix(in srgb, var(--hb-bad) 15%, transparent); }
  /* The row an action was done on, or a new live row, lights up and fades out
     over a second. The card removes the class when the second is over. */
  tr.flash-good, .knownrow.flash-good { animation: hbfade-good 1s ease-out; }
  tr.flash-bad, .knownrow.flash-bad { animation: hbfade-bad 1s ease-out; }
  tr.flash-info { animation: hbfade-info 1s ease-out; }
  @keyframes hbfade-good {
    from { background-color: color-mix(in srgb, var(--hb-good) 28%, transparent); }
    to { background-color: transparent; }
  }
  @keyframes hbfade-bad {
    from { background-color: color-mix(in srgb, var(--hb-bad) 28%, transparent); }
    to { background-color: transparent; }
  }
  @keyframes hbfade-info {
    from { background-color: color-mix(in srgb, var(--primary-color) 22%, transparent); }
    to { background-color: transparent; }
  }
  /* No motion: the highlight stays as it is for that second, then goes. */
  @media (prefers-reduced-motion: reduce) {
    tr.flash-good, .knownrow.flash-good, tr.flash-bad, .knownrow.flash-bad, tr.flash-info {
      animation: none;
    }
    tr.flash-good, .knownrow.flash-good {
      background-color: color-mix(in srgb, var(--hb-good) 28%, transparent);
    }
    tr.flash-bad, .knownrow.flash-bad {
      background-color: color-mix(in srgb, var(--hb-bad) 28%, transparent);
    }
    tr.flash-info { background-color: color-mix(in srgb, var(--primary-color) 22%, transparent); }
  }
  .iconbtn[aria-disabled="true"] { opacity: 0.4; cursor: default; }
  td.actions, td.buttons { white-space: nowrap; }
  .lists {
    display: grid; gap: 0 var(--hb-s6);
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  }
  .lists .section, .section { min-width: 0; }
  .known { padding: var(--hb-s1) 0 var(--hb-s2); }
  .knownrow {
    display: flex; align-items: center; justify-content: space-between; gap: var(--hb-s2);
    min-width: 0; min-height: 36px;
  }
  .knownrow .domain {
    min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font-family: var(--code-font-family, monospace);
  }
  /* Narrow log (a phone, or a narrow column). The Query log shows two lines
     per entry, the same cells as on a wide card:
     line 1: client (its name, or the address) and the time;
     line 2: status badge and domain. The action icon sits at the right, over
     both lines. The badge column has a fixed width, so the domains line up. */
  /* Below 760 px the table cannot give the domain enough room (it needs about
     14rem next to the time, client, type, status and duration), so the log
     drops to two lines earlier than the rest of the card (560 px). */
  @container (max-width: 760px) {
    table.log thead { display: none; }
    table.log, table.log tbody { display: block; }
    table.log tr {
      display: grid; grid-template-columns: 6.5rem minmax(0, 1fr) auto 2.5rem;
      grid-template-areas: "client client time actions" "status domain domain actions";
      align-items: center; gap: var(--hb-s1) var(--hb-s2); padding: var(--hb-s2) 0;
      border-bottom: 1px solid var(--divider-color);
    }
    table.log td { display: block; border: 0; padding: 0; white-space: normal; }
    table.log td.client { grid-area: client; max-width: none; }
    table.log td.domain {
      grid-area: domain; width: auto; max-width: none; white-space: nowrap;
    }
    table.log td.time {
      grid-area: time; display: flex; flex-direction: row-reverse; justify-content: flex-start;
      align-items: baseline; gap: var(--hb-s2); white-space: nowrap;
      color: var(--secondary-text-color); font-size: var(--hb-fs-label);
    }
    table.log td.time .count { margin-left: 0; }
    table.log td.status { grid-area: status; min-width: 0; }
    table.log td.actions {
      grid-area: actions; align-self: center; justify-self: end; min-width: 2.5rem; text-align: right;
    }
    table.log td.actions button, table.log td.actions .iconbtn { margin: 0; }
    table.log td.type, table.log td.ms { display: none; }
    table.log td.client .sub { display: none; }
  }
  @container (max-width: 560px) {
    .body { padding: 0 var(--hb-s3) var(--hb-s3); }
    button, .filters input, .filters select, .panel select { min-height: 40px; }
    .iconbtn { width: 40px; height: 40px; }
    .scroll { overflow-x: visible; }
    /* The requests: client, domain, then level and age, then the buttons. */
    table.req thead { display: none; }
    table.req, table.req tbody { display: block; }
    table.req tr {
      display: grid; grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas: "client client" "domain domain" "level age" "buttons buttons";
      align-items: center; gap: var(--hb-s1) var(--hb-s3); padding: var(--hb-s3) 0;
      border-bottom: 1px solid var(--divider-color);
    }
    table.req td { display: block; border: 0; padding: 0; white-space: normal; }
    table.req td.client { grid-area: client; max-width: none; }
    table.req td.domain {
      grid-area: domain; width: auto; max-width: none; white-space: nowrap;
    }
    table.req td.level {
      grid-area: level; max-width: none; color: var(--secondary-text-color);
      white-space: nowrap;
    }
    table.req td.age { grid-area: age; color: var(--secondary-text-color); }
    table.req td.buttons { grid-area: buttons; padding-top: var(--hb-s2); }
    .filters input[type="search"]:first-child { flex-basis: 100%; }
    .filters input[type="search"] { flex: 1 1 40%; }
  }
  ${DASHBOARD_STYLE}
  ${MORE_STYLE}
  ${TABS_STYLE}
  @container (max-width: 560px) {
    .tablabel { display: none; }
    button.tab { flex: 1 1 0; }
    .toolbar > .btngroup { width: 100%; margin-left: 0; }
    .toolbar .btngroup button { flex: 1 1 0; }
  }
  [hidden] { display: none !important; }
`;
