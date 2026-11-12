/* Styles of the HA-Blocky card (plain text, no data is ever added to them). */

export const STYLE = `
  :host { display: block; }
  .body { padding: 0 16px 16px; }
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
  [hidden] { display: none !important; }
`;
