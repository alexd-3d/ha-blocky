/*
 * Styles of the dashboard toolbar, the status badge and the icon buttons of
 * the Query log, the known-domains list and the cards of the Settings tab
 * (plain text, no data is ever added to them). The colour of a badge is the
 * colour of its kind of query: the class `c-<category>` maps it to `--c`.
 */

export const TABS_STYLE = `
  .ibtn {
    display: inline-grid; place-items: center; flex: 0 0 auto; box-sizing: border-box;
    width: var(--hb-control); height: var(--hb-control); min-width: var(--hb-control);
    padding: 0; border-radius: var(--hb-radius-s);
    --mdc-icon-size: 22px;
  }
  .ibtn:focus-visible, .ksum:focus-visible { outline: 2px solid var(--primary-color); }
  .tbtn.flash-good { animation: hbfade-good 1s ease-out; }
  .tbtn.flash-bad { animation: hbfade-bad 1s ease-out; }

  .dtools { display: grid; gap: var(--hb-s2); min-width: 0; }
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--hb-s2) var(--hb-s3); min-width: 0; }
  .tgroup { display: flex; flex-wrap: wrap; align-items: center; gap: var(--hb-s2); min-width: 0; }
  .toolbar > .btngroup { width: auto; flex: 0 0 auto; margin-left: auto; }
  .toolbar .btngroup button { flex: 0 0 auto; min-width: 56px; padding: 0 var(--hb-s3); }
  .pausebox { display: inline-flex; align-items: center; gap: var(--hb-s2); }

  /* A status badge: a quiet tinted pill. It only tells; it has no border, no
     hover and no pointer, so it cannot be taken for an action button (see
     "button" and ".abtn" in ha-blocky-style.js). The text is the colour of its
     kind of query, mixed with the text colour of the theme to stay readable. */
  .badge {
    display: inline-block; box-sizing: border-box; max-width: 100%;
    padding: 2px var(--hb-s2); border: 0; border-radius: var(--hb-radius-pill);
    background: color-mix(in srgb, var(--c) 16%, transparent);
    color: color-mix(in srgb, var(--c) 70%, var(--primary-text-color));
    font-size: var(--hb-fs-label); font-weight: var(--hb-fw-medium); line-height: 16px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: middle;
    cursor: default; user-select: none; pointer-events: none;
  }

  /* The known domains: one divider between the clients, no boxes. */
  .kn { display: grid; gap: 0; }
  details.kitem { min-width: 0; border-top: 1px solid var(--divider-color); }
  .ksum {
    display: flex; align-items: center; gap: var(--hb-s3); min-height: 48px; padding: var(--hb-s2) 0;
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
    flex: 0 0 auto; min-width: 1.6em; padding: 2px var(--hb-s2); border-radius: var(--hb-radius-pill);
    text-align: center; font-size: var(--hb-fs-label); font-weight: var(--hb-fw-medium);
    font-variant-numeric: tabular-nums; cursor: default; background: var(--hb-tonal);
  }
  .kbody { padding: 0 0 var(--hb-s2) var(--hb-s6); min-width: 0; }

  .settings {
    display: grid; gap: var(--hb-s4); align-items: start; min-width: 0; max-width: 1100px;
    grid-template-columns: repeat(auto-fit, minmax(min(360px, 100%), 1fr));
  }
  .settings > * { min-width: 0; }
  .scard {
    box-sizing: border-box; min-width: 0; padding: var(--hb-s4); border-radius: var(--hb-radius-m);
    border: 1px solid var(--divider-color); background: var(--card-background-color);
  }
  .scard h3 { margin: 0 0 var(--hb-s1); font-size: var(--hb-fs-title); font-weight: var(--hb-fw-medium); }
  .scard .hint { color: var(--secondary-text-color); font-size: var(--hb-fs-label); }
  .scard .field .hint { margin-top: var(--hb-s1); }
  .group { margin-top: var(--hb-s6); min-width: 0; }
  .gtitle {
    margin: 0 0 var(--hb-s2); font-size: var(--hb-fs-label); font-weight: var(--hb-fw-medium);
    letter-spacing: 0.4px; text-transform: uppercase; color: var(--secondary-text-color);
  }

  @media (prefers-reduced-motion: reduce) {
    .tbtn.flash-good, .tbtn.flash-bad { animation: none; }
    .tbtn.flash-good { background-color: color-mix(in srgb, var(--hb-good) 28%, transparent); }
    .tbtn.flash-bad { background-color: color-mix(in srgb, var(--hb-bad) 28%, transparent); }
    .karrow { transition: none; }
  }
  @container (max-width: 560px) {
    .ibtn { width: 40px; height: 40px; min-width: 40px; }
    .toolbar .btngroup button { min-height: 40px; }
    .scard { padding: var(--hb-s3); }
  }
`;
