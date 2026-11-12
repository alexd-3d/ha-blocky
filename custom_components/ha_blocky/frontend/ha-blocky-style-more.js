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
  tr.flash-info { background-color: color-mix(in srgb, var(--primary-color) 22%, transparent); }
  @media (prefers-reduced-motion: reduce) {
    button.live.on { animation: none; }
  }
`;
