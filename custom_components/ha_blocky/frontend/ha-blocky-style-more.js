/*
 * Styles of the Settings tab, the Help tab and the Live button (plain text,
 * no data is ever added to them).
 */

export const MORE_STYLE = `
  .helppage { display: grid; gap: 0; min-width: 0; }
  .helppage > * { min-width: 0; }
  .field { margin: var(--hb-s4) 0; }
  .flabel {
    display: flex; flex-direction: column; gap: var(--hb-s1);
    font-weight: var(--hb-fw-medium);
  }
  .flabel input[type="number"], .flabel input[type="text"] {
    width: 100%; max-width: 240px; font-weight: 400;
  }
  .field.check .flabel { flex-direction: row-reverse; justify-content: flex-end; align-items: center; gap: var(--hb-s3); }
  .field.check input { width: 22px; height: 22px; margin: 0; }
  .field .hint { margin-top: var(--hb-s1); }
  .colors { display: grid; gap: var(--hb-s3); grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
  .crow { display: flex; align-items: center; gap: var(--hb-s3); min-width: 0; min-height: 40px; cursor: pointer; }
  .crow .cname { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .crow input[type="color"] {
    flex: 0 0 auto; box-sizing: border-box; width: 36px; height: 36px; padding: 0;
    cursor: pointer; border: 0; border-radius: var(--hb-radius-s); background: none;
    -webkit-appearance: none; appearance: none;
  }
  .crow input[type="color"]::-webkit-color-swatch-wrapper { padding: 0; }
  .crow input[type="color"]::-webkit-color-swatch { border: none; border-radius: 8px; }
  .crow input[type="color"]::-moz-color-swatch { border: none; border-radius: 8px; }
  svg.mbar.pbar { display: block; width: 100%; max-width: 100%; height: 12px; border-radius: 6px; margin: var(--hb-s1) 0 var(--hb-s2); }
  .btnrow { display: flex; flex-wrap: wrap; align-items: center; gap: var(--hb-s2); margin-top: var(--hb-s4); }
  .btnrow button { flex: 0 0 auto; }
  .settings .btngroup { max-width: 240px; margin: var(--hb-s2) 0; }
  .rowhint { color: var(--secondary-text-color); }

  /* Help and rules: a list of sections with one divider between them. */
  details.sec { border-top: 1px solid var(--divider-color); }
  details.sec > summary {
    min-height: 48px; display: flex; align-items: center; cursor: pointer;
    font-weight: var(--hb-fw-medium);
  }
  details.sec > summary:hover { color: var(--primary-color); }
  details.sec > summary:focus-visible { outline: 2px solid var(--primary-color); }
  details.sec p, details.sec ul { margin: 0 0 var(--hb-s3); line-height: 1.45; }
  details.sec ul { padding-left: 20px; }
  .srcrow { display: flex; flex-wrap: wrap; align-items: center; gap: var(--hb-s1) var(--hb-s2); margin: 0 0 var(--hb-s3); }
  .srcname { flex: 1 1 100%; font-weight: var(--hb-fw-medium); }
  .srcurl {
    flex: 1 1 200px; min-width: 0; font-family: var(--code-font-family, monospace);
    font-size: var(--hb-fs-label); word-break: break-all; user-select: all;
  }

  /* Protection: clients and levels, rules, the block and the status. */
  table.prot td { vertical-align: middle; }
  table.prot select { max-width: 100%; }
  table.prot td.askcell { white-space: normal; }
  .levellegend { margin: var(--hb-s2) 0; padding-left: 20px; line-height: 1.45; }
  .flabel input.widefield { max-width: 100%; }
  .rulerow { display: flex; align-items: center; gap: var(--hb-s2); min-height: 40px; }
  .rulerow .domain {
    flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; font-family: var(--code-font-family, monospace);
  }
  details.sec .btnrow input[type="text"] { flex: 1 1 200px; }
  /* A banner tells a state of the setup: tinted, no border, nothing to press. */
  .banner {
    margin: var(--hb-s3) 0; padding: var(--hb-s3) var(--hb-s4); border-radius: var(--hb-radius-s);
    font-weight: var(--hb-fw-medium); background: var(--hb-surface); cursor: default;
  }
  .banner.ok { color: var(--hb-good); background: color-mix(in srgb, var(--hb-good) 14%, transparent); }
  .banner.waiting {
    color: var(--primary-text-color);
    background: color-mix(in srgb, var(--warning-color, #f5a623) 18%, transparent);
  }
  /* The block to paste into Blocky: the format, then the text, then the notes. */
  .blockbox { margin-top: var(--hb-s3); }
  .blockbox textarea {
    width: 100%; margin-top: var(--hb-s2);
    font-family: var(--code-font-family, monospace); font-size: var(--hb-fs-label);
  }
  table.setupcheck td { padding-top: var(--hb-s2); padding-bottom: var(--hb-s2); }
  table.setupcheck td:last-child { text-align: right; font-weight: var(--hb-fw-medium); }
  table.compare th, table.compare td {
    white-space: normal; vertical-align: top; min-width: 9rem; line-height: 1.35;
  }
  table.compare th.levelname { white-space: nowrap; min-width: 0; color: var(--primary-text-color); }
  table.compare td.wrap { max-width: 16rem; }

  button.live.on {
    color: var(--hb-good); border-color: var(--hb-good);
    background: color-mix(in srgb, var(--hb-good) 16%, transparent);
    animation: hbpulse 1.4s ease-in-out infinite;
  }
  @keyframes hbpulse {
    0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--hb-good) 60%, transparent); }
    70% { box-shadow: 0 0 0 8px transparent; }
    100% { box-shadow: 0 0 0 0 transparent; }
  }
  @media (prefers-reduced-motion: reduce) {
    button.live.on { animation: none; }
  }
  /* The "ignore query type" toggle: a T with a line through it while on. */
  .ibtn.ignoretype { position: relative; }
  .ibtn.ignoretype.on {
    color: var(--primary-color); border-color: var(--primary-color);
    background: var(--hb-tonal);
  }
  .ibtn.ignoretype.on::after {
    content: ""; position: absolute; left: 7px; right: 7px; top: 50%; height: 2px;
    background: currentColor; transform: rotate(-40deg); pointer-events: none;
  }
  .ibtn.ignoretype:disabled { opacity: 0.4; }
  table.prot td.nametd { min-width: 9rem; }
  table.prot input.nameedit { width: 100%; border-color: var(--hb-outline); }
  table.prot input.nameedit:focus-visible { border-color: var(--primary-color); }
  @container (max-width: 560px) {
    .btnrow button { min-height: 40px; }
    table.prot select { min-height: 40px; }
  }
`;
