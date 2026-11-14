/*
 * Styles of the Dashboard tab (plain text, no data is ever added to them).
 *
 * The colour of a query category comes from the custom properties
 * `--hb-color-<category>` defined in ha-blocky-style.js; every place that
 * shows a category (tiles, bars, legend, popover) uses the class
 * `c-<category>`, which maps it to `--c`.
 */

export const DASHBOARD_STYLE = `
  .c-resolved { --c: var(--hb-color-resolved); }
  .c-cached { --c: var(--hb-color-cached); }
  .c-local { --c: var(--hb-color-local); }
  .c-blocked { --c: var(--hb-color-blocked); }
  .c-other { --c: var(--hb-color-other); }
  .c-total { --c: var(--primary-color); }

  .dash {
    position: relative; display: grid; gap: var(--hb-s4); min-width: 0; overflow-x: clip;
  }
  .dash > * { min-width: 0; }
  .dash .hint { margin: 0; color: var(--secondary-text-color); font-size: var(--hb-fs-label); }

  .bswitch {
    --c: var(--disabled-text-color, #9e9e9e);
    display: inline-flex; align-items: center; justify-content: space-between; gap: 12px;
    box-sizing: border-box; max-width: 100%; min-height: 40px; padding: var(--hb-s1) var(--hb-s3);
    border: 1px solid color-mix(in srgb, var(--c) 60%, transparent); border-radius: var(--hb-radius-m);
    color: var(--primary-text-color); font-size: var(--hb-fs-body); font-weight: var(--hb-fw-medium);
    background: color-mix(in srgb, var(--c) 12%, transparent);
  }
  .bswitch.on { --c: var(--hb-good); }
  .bswitch.off { --c: var(--hb-bad); }
  .bswitch:hover { background: color-mix(in srgb, var(--c) 18%, transparent); }
  .bswitch:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .pill { display: inline-flex; align-items: center; gap: var(--hb-s2); min-width: 0; text-align: left; }
  .pill::before {
    content: ""; flex: 0 0 auto; width: 12px; height: 12px; border-radius: 50%;
    background: var(--c);
  }
  .track {
    position: relative; flex: 0 0 auto; width: 44px; height: 26px; border-radius: 13px;
    background: var(--c);
  }
  .knob {
    position: absolute; top: 3px; left: 3px; width: 20px; height: 20px;
    border-radius: 50%; background: var(--text-primary-color, #fff); transition: transform 0.2s;
  }
  .bswitch.on .knob { transform: translateX(18px); }

  /* A segmented control: the pressed button is tonal. */
  .btngroup { display: flex; width: 100%; }
  .btngroup button {
    flex: 1 1 0; min-width: 0; padding: 0 var(--hb-s1); margin-left: -1px;
    border-radius: 0; white-space: nowrap;
  }
  .btngroup button:first-child { margin-left: 0; border-radius: var(--hb-radius-s) 0 0 var(--hb-radius-s); }
  .btngroup button:last-child { border-radius: 0 var(--hb-radius-s) var(--hb-radius-s) 0; }
  .btngroup button.on {
    position: relative; z-index: 1;
    color: var(--primary-text-color); background: var(--hb-tonal);
    border-color: var(--primary-color);
  }
  .listbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: var(--hb-s2); }
  .listbar .btngroup { width: auto; }
  .listbar .btngroup button { flex: 0 0 auto; min-width: 44px; min-height: 32px; padding: 0 var(--hb-s3); }

  .tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--hb-s3); }
  .tile {
    display: flex; align-items: center; gap: var(--hb-s3); min-width: 0; padding: var(--hb-s3) var(--hb-s4);
    border-radius: var(--hb-radius-m); background: var(--hb-surface);
  }
  .chip {
    flex: 0 0 auto; display: grid; place-items: center; width: 40px; height: 40px;
    border-radius: var(--hb-radius-m); color: var(--c); --mdc-icon-size: 24px;
    background: color-mix(in srgb, var(--c) 18%, transparent);
  }
  .tbody { min-width: 0; }
  .tlabel, .tsub { color: var(--secondary-text-color); }
  .tlabel { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--hb-fs-label); }
  .tsub { font-size: var(--hb-fs-label); overflow-wrap: anywhere; }
  .tvalue {
    font-size: var(--hb-fs-value); font-weight: var(--hb-fw-medium); line-height: 1.15;
    font-variant-numeric: tabular-nums;
  }

  .part { min-width: 0; }
  .phead { display: flex; align-items: center; gap: var(--hb-s2); }
  .phead h3 { margin: 0; font-size: var(--hb-fs-title); font-weight: var(--hb-fw-medium); }
  .help {
    flex: none; box-sizing: border-box; width: 32px; height: 32px; min-width: 32px; min-height: 0;
    padding: 0; border: 0; border-radius: 50%; display: inline-flex; align-items: center;
    justify-content: center; line-height: 1; --mdc-icon-size: 22px;
    color: var(--secondary-text-color);
  }
  .help:hover { background: var(--divider-color); }
  .help:focus-visible { outline: 2px solid var(--primary-color); }
  .help[aria-expanded="true"] { color: var(--primary-color); }
  .info {
    margin: var(--hb-s2) 0; padding: var(--hb-s2) var(--hb-s3); border-radius: var(--hb-radius-s);
    font-size: var(--hb-fs-body); background: var(--hb-tonal);
  }
  .pbody { margin-top: var(--hb-s2); }

  .chart { min-width: 0; padding: 0; }
  .plot { position: relative; }
  svg.bars { display: block; width: 100%; height: 160px; }
  svg.bars .grid {
    stroke: var(--divider-color); stroke-width: 1; vector-effect: non-scaling-stroke;
  }
  svg.bars .seg, svg.mbar .seg { fill: var(--c); }
  svg.bars .hit { fill: transparent; cursor: pointer; outline: none; }
  svg.bars .hit:hover, svg.bars .hit:focus-visible {
    fill: color-mix(in srgb, var(--primary-text-color) 10%, transparent);
  }
  .peak {
    position: absolute; top: 0; left: 0; padding: 0 var(--hb-s1); pointer-events: none;
    font-size: var(--hb-fs-label); color: var(--secondary-text-color);
    background: color-mix(in srgb, var(--card-background-color) 70%, transparent);
  }
  .axis { display: flex; margin-top: var(--hb-s1); }
  .tick {
    flex: 1 1 0; min-width: 0; display: flex; justify-content: center;
    font-size: var(--hb-fs-label); white-space: nowrap; color: var(--secondary-text-color);
  }
  .legend { display: flex; flex-wrap: wrap; gap: var(--hb-s1) var(--hb-s4); margin-top: var(--hb-s3); font-size: var(--hb-fs-label); }
  .legend .line { cursor: help; border-radius: 4px; }
  .legend .line:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .line { display: flex; align-items: center; gap: var(--hb-s2); }
  .sw { flex: 0 0 auto; width: 10px; height: 10px; border-radius: 3px; background: var(--c); }
  .lvalue { font-weight: var(--hb-fw-medium); font-variant-numeric: tabular-nums; }
  .lshare { min-width: 3em; text-align: right; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }

  .tops { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--hb-s6); }
  .toplist { display: grid; gap: 2px; }
  .trow { min-width: 0; padding: var(--hb-s2); border-radius: var(--hb-radius-s); cursor: pointer; outline: none; }
  .trow:hover { background: var(--hb-hover); }
  /* A client of the list opens the Query log for it: it reads as a link. */
  .trow.client:hover .tname { color: var(--primary-color); text-decoration: underline; }
  .trow:focus-visible { outline: 2px solid var(--primary-color); }
  .thead { display: flex; align-items: baseline; justify-content: space-between; gap: var(--hb-s2); }
  .tname {
    min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font-weight: var(--hb-fw-medium);
  }
  .trow:not(.client) .tname { font-family: var(--code-font-family, monospace); }
  .tcount { flex: 0 0 auto; font-weight: var(--hb-fw-medium); font-variant-numeric: tabular-nums; }
  .taddr, .mono { font-family: var(--code-font-family, monospace); }
  .taddr { font-size: var(--hb-fs-label); color: var(--secondary-text-color); }
  svg.mbar { display: block; width: 100%; height: 4px; margin-top: 4px; border-radius: 2px; }
  svg.mbar .track { fill: var(--divider-color); }

  .pop {
    position: absolute; z-index: 5; box-sizing: border-box; pointer-events: none;
    min-width: 180px; max-width: min(320px, 100%); padding: var(--hb-s3);
    border: 1px solid var(--divider-color); border-radius: var(--hb-radius-s); font-size: var(--hb-fs-label);
    color: var(--primary-text-color); background: var(--card-background-color);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  }
  .pop .ptitle { margin-bottom: var(--hb-s1); font-weight: var(--hb-fw-medium); word-break: break-all; }
  .pop .line { margin: 2px 0; }
  .pop .lname { flex: 1 1 auto; }
  .pop .lvalue { margin-left: 12px; text-align: right; }
  .pop .reason .lvalue { word-break: break-word; }
  .pop .total { margin-top: var(--hb-s1); padding-top: var(--hb-s1); border-top: 1px solid var(--divider-color); }

  .dfoot { color: var(--secondary-text-color); font-size: var(--hb-fs-label); text-align: center; }

  @container (max-width: 560px) {
    .tiles { gap: var(--hb-s2); }
    .tile { gap: var(--hb-s2); padding: var(--hb-s3); }
    .chip { width: 32px; height: 32px; border-radius: var(--hb-radius-s); --mdc-icon-size: 20px; }
    .tvalue { font-size: 24px; }
    .help { width: 40px; height: 40px; }
    .listbar .btngroup button { min-height: 40px; }
    .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .tops { grid-template-columns: minmax(0, 1fr); }
  }
  @media (prefers-reduced-motion: reduce) {
    .knob { transition: none; }
  }
`;
