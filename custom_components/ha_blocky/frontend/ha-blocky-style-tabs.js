/*
 * Styles of the dashboard toolbar, the status badge and the icon buttons of
 * the Query log, the known-domains list and the cards of the Settings tab
 * (plain text, no data is ever added to them). The colour of a badge is the
 * colour of its kind of query: the class `c-<category>` maps it to `--c`.
 */

export const TABS_STYLE = `
  .ibtn {
    display: inline-grid; place-items: center; flex: 0 0 auto; box-sizing: border-box;
    width: 38px; height: 38px; min-width: 38px; padding: 0; border-radius: 8px;
    --mdc-icon-size: 22px; transition: background-color 0.9s ease-out;
  }
  .ibtn:focus-visible, .ksum:focus-visible { outline: 2px solid var(--primary-color); }
  .tbtn.flash-good { background-color: color-mix(in srgb, var(--hb-good) 28%, transparent); }
  .tbtn.flash-bad { background-color: color-mix(in srgb, var(--hb-bad) 28%, transparent); }

  .dtools { display: grid; gap: 6px; min-width: 0; }
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; min-width: 0; }
  .tgroup { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-width: 0; }
  .toolbar > .btngroup { width: auto; flex: 0 0 auto; margin-left: auto; }
  .toolbar .btngroup button { flex: 0 0 auto; min-width: 56px; min-height: 36px; padding: 4px 12px; }
  .pausebox { display: inline-flex; align-items: center; gap: 6px; }
  .pausebox select {
    min-height: 36px; padding: 4px 8px; font: inherit; color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: 6px;
  }

  .badge {
    display: inline-block; box-sizing: border-box; padding: 1px 8px; border-radius: 999px;
    border: 1px solid var(--c); background: transparent; color: var(--c);
    font-size: 0.8em; font-weight: 500; line-height: 1.5; white-space: nowrap;
  }
  ha-icon.statusicon { color: var(--c); }

  .kn { display: grid; gap: 8px; }
  details.kitem { min-width: 0; border: 1px solid var(--divider-color); border-radius: 8px; }
  .ksum {
    display: flex; align-items: center; gap: 12px; min-height: 44px; padding: 6px 12px;
    cursor: pointer; list-style: none;
  }
  .ksum::-webkit-details-marker { display: none; }
  .ksum::marker { content: ""; }
  .karrow {
    flex: 0 0 auto; --mdc-icon-size: 20px; color: var(--secondary-text-color);
    transition: transform 0.15s;
  }
  details[open] > .ksum .karrow { transform: rotate(90deg); }
  .kname { flex: 1 1 auto; min-width: 0; }
  .kname .main, .kname .sub { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .kcount {
    flex: 0 0 auto; min-width: 1.6em; padding: 1px 8px; border-radius: 999px;
    text-align: center; font-size: 0.85em; font-weight: 600;
    background: color-mix(in srgb, var(--primary-color) 16%, transparent);
  }
  .kbody { padding: 0 12px 8px; min-width: 0; }

  .settings {
    display: grid; gap: 16px; align-items: start; min-width: 0; max-width: 1100px;
    grid-template-columns: repeat(auto-fit, minmax(min(360px, 100%), 1fr));
  }
  .settings > * { min-width: 0; }
  .scard {
    box-sizing: border-box; min-width: 0; padding: 16px; border-radius: 12px;
    border: 1px solid var(--divider-color); background: var(--card-background-color);
  }
  .scard h3 { margin: 0 0 4px; font-size: 1.1em; font-weight: 600; }
  .scard .hint { color: var(--secondary-text-color); font-size: 0.85em; }
  .scard .field .hint { margin-top: 4px; }
  .group { margin-top: 20px; min-width: 0; }
  .gtitle { margin: 0 0 8px; font-size: 0.95em; font-weight: 600; }

  @media (prefers-reduced-motion: reduce) {
    .ibtn { transition: none; }
    .karrow { transition: none; }
  }
`;
