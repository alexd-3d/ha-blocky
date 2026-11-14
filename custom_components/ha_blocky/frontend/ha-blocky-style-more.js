/*
 * Styles of the Settings tab, the Help tab and the Live button (plain text,
 * no data is ever added to them).
 */

export const MORE_STYLE = `
  .helppage { display: grid; gap: 12px; min-width: 0; }
  .helppage > * { min-width: 0; }
  .field { margin: 16px 0; }
  .flabel { display: flex; flex-direction: column; gap: 6px; font-weight: 500; }
  .flabel input[type="number"], .flabel input[type="text"] {
    box-sizing: border-box; width: 100%; max-width: 240px; min-height: 40px; padding: 8px;
    font: inherit; font-weight: 400; color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: 6px;
  }
  .field.check .flabel { flex-direction: row-reverse; justify-content: flex-end; align-items: center; gap: 10px; }
  .field.check input { width: 22px; height: 22px; margin: 0; }
  .field .hint { margin-top: 2px; }
  .colors { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
  .crow { display: flex; align-items: center; gap: 10px; min-width: 0; cursor: pointer; }
  .crow .cname { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .crow input[type="color"] {
    flex: 0 0 auto; box-sizing: border-box; width: 36px; height: 36px; padding: 0;
    cursor: pointer; border: 0; border-radius: 8px; background: none;
    -webkit-appearance: none; appearance: none;
  }
  .crow input[type="color"]::-webkit-color-swatch-wrapper { padding: 0; }
  .crow input[type="color"]::-webkit-color-swatch { border: none; border-radius: 8px; }
  .crow input[type="color"]::-moz-color-swatch { border: none; border-radius: 8px; }
  svg.mbar.pbar { display: block; width: 100%; max-width: 100%; height: 12px; border-radius: 6px; margin: 4px 0 8px; }
  .btnrow { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 16px; }
  .btnrow button { flex: 0 0 auto; min-height: 40px; }
  .settings .btngroup { max-width: 240px; margin: 6px 0; }
  .rowhint { color: var(--secondary-text-color); }

  details.sec {
    padding: 0 12px; border: 1px solid var(--divider-color); border-radius: 8px;
  }
  details.sec > summary {
    min-height: 44px; display: flex; align-items: center; cursor: pointer;
    font-weight: 600;
  }
  details.sec > summary:focus-visible { outline: 2px solid var(--primary-color); }
  details.sec p, details.sec ul { margin: 0 0 12px; line-height: 1.45; }
  details.sec ul { padding-left: 20px; }
  .srcrow { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; margin: 0 0 12px; }
  .srcname { flex: 1 1 100%; font-weight: 500; }
  .srcurl {
    flex: 1 1 200px; min-width: 0; font-family: var(--code-font-family, monospace);
    font-size: 0.85em; word-break: break-all; user-select: all;
  }

  /* Protection: clients and levels, rules, the block and the status. */
  table.prot td { vertical-align: middle; }
  table.prot select { min-height: 36px; max-width: 100%; font: inherit; }
  table.prot td.askcell { white-space: normal; }
  .levellegend { margin: 8px 0; padding-left: 20px; line-height: 1.45; }
  .flabel input.widefield { max-width: 100%; }
  .rulerow { display: flex; align-items: center; gap: 8px; min-height: 36px; }
  .rulerow .domain {
    flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; font-family: var(--code-font-family, monospace);
  }
  details.sec .btnrow input[type="text"] {
    flex: 1 1 200px; min-width: 0; box-sizing: border-box; min-height: 40px; padding: 8px;
    font: inherit; color: var(--primary-text-color); background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: 6px;
  }
  .banner { margin: 12px 0; padding: 10px 12px; border-radius: 6px; font-weight: 500; }
  .banner.ok { color: var(--hb-good); border: 1px solid var(--hb-good); }
  .banner.waiting { color: var(--primary-text-color); border: 1px solid var(--warning-color, #f5a623); }
  .blockbox textarea {
    box-sizing: border-box; width: 100%; margin-top: 8px; padding: 8px;
    font-family: var(--code-font-family, monospace); font-size: 0.85em;
    color: var(--primary-text-color); background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: 6px;
  }
  table.setupcheck td:last-child { text-align: right; font-weight: 500; }
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
    background: color-mix(in srgb, var(--primary-color) 14%, transparent);
  }
  .ibtn.ignoretype.on::after {
    content: ""; position: absolute; left: 7px; right: 7px; top: 50%; height: 2px;
    background: currentColor; transform: rotate(-40deg); pointer-events: none;
  }
  .ibtn.ignoretype:disabled { opacity: 0.4; }
  table.prot td.nametd { min-width: 9rem; }
  table.prot input.nameedit {
    width: 100%; box-sizing: border-box; padding: 6px 8px; font: inherit;
    color: var(--primary-text-color); background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: 6px;
  }
`;
