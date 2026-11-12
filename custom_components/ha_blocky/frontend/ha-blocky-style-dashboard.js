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
    position: relative; display: grid; gap: 12px; min-width: 0; overflow-x: clip;
  }
  .dash > * { min-width: 0; }
  .dash .hint { margin: 0; color: var(--secondary-text-color); font-size: 0.85em; }

  .bswitch {
    --c: var(--disabled-text-color, #9e9e9e);
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    box-sizing: border-box; width: 100%; min-height: 56px; padding: 8px 16px;
    border: 2px solid var(--c); border-radius: 12px;
    color: var(--primary-text-color); font-size: 1.1em; font-weight: 600;
    background: color-mix(in srgb, var(--c) 14%, transparent);
  }
  .bswitch.on { --c: var(--hb-good); }
  .bswitch.off { --c: var(--hb-bad); }
  .bswitch:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .pill { display: inline-flex; align-items: center; gap: 10px; min-width: 0; text-align: left; }
  .pill::before {
    content: ""; flex: 0 0 auto; width: 12px; height: 12px; border-radius: 50%;
    background: var(--c);
  }
  .track {
    position: relative; flex: 0 0 auto; width: 52px; height: 30px; border-radius: 15px;
    background: var(--c);
  }
  .knob {
    position: absolute; top: 3px; left: 3px; width: 24px; height: 24px;
    border-radius: 50%; background: #fff; transition: transform 0.2s;
  }
  .bswitch.on .knob { transform: translateX(22px); }

  .btngroup { display: flex; width: 100%; }
  .btngroup button {
    flex: 1 1 0; min-width: 0; min-height: 40px; padding: 6px 4px; margin-left: -1px;
    border-radius: 0; font-size: 0.95em; white-space: nowrap;
  }
  .btngroup button:first-child { margin-left: 0; border-radius: 8px 0 0 8px; }
  .btngroup button:last-child { border-radius: 0 8px 8px 0; }
  .btngroup button.on {
    position: relative; z-index: 1; font-weight: 600;
    color: var(--text-primary-color); background: var(--primary-color);
    border-color: var(--primary-color);
  }
  .listbar { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
  .listbar .btngroup { width: auto; }
  .listbar .btngroup button { flex: 0 0 auto; min-width: 44px; min-height: 32px; padding: 4px 12px; }

  .tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
  .tile {
    display: flex; align-items: center; gap: 12px; min-width: 0; padding: 12px;
    border: 1px solid var(--divider-color); border-radius: 12px;
    background: var(--card-background-color);
  }
  .chip {
    flex: 0 0 auto; display: grid; place-items: center; width: 40px; height: 40px;
    border-radius: 12px; color: var(--c); --mdc-icon-size: 24px;
    background: color-mix(in srgb, var(--c) 18%, transparent);
  }
  .tbody { min-width: 0; }
  .tlabel, .tsub { color: var(--secondary-text-color); }
  .tlabel { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.85em; }
  .tsub { font-size: 0.8em; overflow-wrap: anywhere; }
  .tvalue { font-size: 1.8em; font-weight: 700; line-height: 1.15; }

  .part { min-width: 0; }
  .phead { display: flex; align-items: center; gap: 8px; }
  .phead h3 { margin: 0; font-size: 1.05em; font-weight: 600; }
  .help {
    flex: none; box-sizing: border-box; width: 24px; height: 24px; min-width: 24px;
    padding: 0; border-radius: 50%; display: inline-flex; align-items: center;
    justify-content: center; font-size: 0.85em; line-height: 1;
    color: var(--secondary-text-color);
  }
  .help[aria-expanded="true"] {
    color: var(--text-primary-color); background: var(--primary-color);
    border-color: var(--primary-color);
  }
  .info {
    margin: 6px 0; padding: 8px 12px; border-radius: 8px; font-size: 0.9em;
    background: color-mix(in srgb, var(--primary-color) 10%, transparent);
  }
  .pbody { margin-top: 8px; }

  .chart { min-width: 0; padding: 0 12px; }
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
    position: absolute; top: 0; left: 0; padding: 0 4px; pointer-events: none;
    font-size: 0.75em; color: var(--secondary-text-color);
    background: color-mix(in srgb, var(--card-background-color) 70%, transparent);
  }
  .axis { display: flex; margin-top: 4px; }
  .tick {
    flex: 1 1 0; min-width: 0; display: flex; justify-content: center;
    font-size: 0.75em; white-space: nowrap; color: var(--secondary-text-color);
  }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 8px; font-size: 0.85em; }
  .line { display: flex; align-items: center; gap: 6px; }
  .sw { flex: 0 0 auto; width: 10px; height: 10px; border-radius: 3px; background: var(--c); }
  .lvalue { font-weight: 600; }
  .lshare { min-width: 3em; text-align: right; color: var(--secondary-text-color); }

  .tops { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
  .toplist { display: grid; gap: 2px; }
  .trow { min-width: 0; padding: 6px 8px; border-radius: 8px; cursor: pointer; outline: none; }
  .trow:hover { background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); }
  .trow:focus-visible { outline: 2px solid var(--primary-color); }
  .thead { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .tname {
    min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font-weight: 500;
  }
  .trow:not(.client) .tname { font-family: var(--code-font-family, monospace); font-size: 0.9em; }
  .tcount { flex: 0 0 auto; font-weight: 700; }
  .taddr, .mono { font-family: var(--code-font-family, monospace); }
  .taddr { font-size: 0.75em; color: var(--secondary-text-color); }
  svg.mbar { display: block; width: 100%; height: 4px; margin-top: 4px; border-radius: 2px; }
  svg.mbar .track { fill: var(--divider-color); }

  .pop {
    position: absolute; z-index: 5; box-sizing: border-box; pointer-events: none;
    min-width: 180px; max-width: min(320px, 100%); padding: 10px 12px;
    border: 1px solid var(--divider-color); border-radius: 8px; font-size: 0.85em;
    color: var(--primary-text-color); background: var(--card-background-color);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  }
  .pop .ptitle { margin-bottom: 4px; font-weight: 600; word-break: break-all; }
  .pop .line { margin: 2px 0; }
  .pop .lname { flex: 1 1 auto; }
  .pop .lvalue { margin-left: 12px; text-align: right; }
  .pop .reason .lvalue { word-break: break-word; }
  .pop .total { margin-top: 4px; padding-top: 4px; border-top: 1px solid var(--divider-color); }

  .dfoot { color: var(--secondary-text-color); font-size: 0.85em; text-align: center; }

  @container (max-width: 560px) {
    .tiles { gap: 8px; }
    .tile { gap: 8px; padding: 10px; }
    .chip { width: 32px; height: 32px; border-radius: 10px; --mdc-icon-size: 20px; }
    .tvalue { font-size: 1.5em; }
    .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .tops { grid-template-columns: minmax(0, 1fr); }
  }
  @media (prefers-reduced-motion: reduce) {
    .knob { transition: none; }
  }
`;
