/*
 * Styles of the Settings tab, the Help tab and the Live button (plain text,
 * no data is ever added to them).
 */

export const MORE_STYLE = `
  .settings, .helppage { display: grid; gap: 12px; min-width: 0; }
  .settings > *, .helppage > * { min-width: 0; }
  .field { margin: 8px 0; }
  .flabel { display: flex; flex-direction: column; gap: 4px; font-weight: 500; }
  .flabel input[type="number"], .flabel input[type="text"] {
    box-sizing: border-box; width: 100%; min-height: 40px; padding: 8px;
    font: inherit; font-weight: 400; color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: 6px;
  }
  .field.check .flabel { flex-direction: row-reverse; justify-content: flex-end; align-items: center; gap: 10px; }
  .field.check input { width: 22px; height: 22px; margin: 0; }
  .field .hint { margin-top: 2px; }
  .colors { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
  .crow { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .crow input[type="color"] {
    flex: 0 0 auto; width: 44px; height: 40px; padding: 0; cursor: pointer;
    border: 1px solid var(--divider-color); border-radius: 6px; background: none;
  }
  svg.mbar.pbar { height: 12px; border-radius: 6px; margin: 8px 0; }
  .btnrow { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; }
  .btnrow button { min-height: 40px; }
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

  button.live { display: inline-flex; align-items: center; gap: 8px; }
  .livedot { width: 10px; height: 10px; border-radius: 50%; background: var(--secondary-text-color); }
  button.live.on { color: var(--hb-good); border-color: var(--hb-good); font-weight: 600; }
  button.live.on .livedot { background: var(--hb-good); animation: hbpulse 1.4s ease-in-out infinite; }
  @keyframes hbpulse {
    0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--hb-good) 60%, transparent); }
    70% { box-shadow: 0 0 0 8px transparent; }
    100% { box-shadow: 0 0 0 0 transparent; }
  }
  tr.flash-info { background-color: color-mix(in srgb, var(--primary-color) 22%, transparent); }
  @media (prefers-reduced-motion: reduce) {
    button.live.on .livedot { animation: none; }
  }
`;
