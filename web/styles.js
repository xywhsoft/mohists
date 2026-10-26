export function installStyles() {
  const node = document.createElement("style");
  node.textContent = `
.mh {color:var(--ink);font-size:.875rem;line-height:1.65;min-width:0}
.mh * {box-sizing:border-box}
.mh h3,.mh h4,.mh p {margin:0}
.mh h3 {font-size:1rem}.mh h4 {font-size:.9rem}
.mh-muted {color:var(--muted);font-size:.8rem}
.mh-stack {display:flex;flex-direction:column;gap:1rem;min-width:0}
.mh-line {display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;min-width:0}
.mh-line .mh-grow {flex:1;min-width:5rem}
.mh-button {display:inline-flex;align-items:center;justify-content:center;gap:.35rem;padding:.4rem .7rem;border:1px solid var(--border-strong);border-radius:var(--radius-sm);background:transparent;color:var(--ink);font:inherit;cursor:pointer;white-space:nowrap}
.mh-button:hover {background:var(--surface-hover)}.mh-button:disabled {opacity:.5;cursor:default}
.mh-button.mh-primary {background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.mh-button.mh-danger,.mh-error {color:var(--danger)}
.mh-error {font-size:.825rem;white-space:pre-wrap;overflow-wrap:anywhere}
.mh-error:empty {display:none}
.mh-tag {display:inline-flex;border-radius:2rem;padding:.1rem .55rem;background:var(--surface-hover);color:var(--muted);font-size:.75rem;white-space:nowrap}
.mh-tag[data-state=succeeded],.mh-tag[data-state=completed] {color:var(--success)}
.mh-tag[data-state=requires_review],.mh-tag[data-state=failed] {color:var(--warning)}
.mh-card {border:1px solid var(--border);border-radius:var(--radius-md);padding:1rem;background:var(--surface-raised);overflow-wrap:anywhere}
.mh-summary {max-width:50rem;margin:1rem auto;width:100%;padding:1rem;display:flex;flex-direction:column;gap:.6rem;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface)}
.mh-summary:empty {display:none}.mh-summary-jobs {display:flex;gap:.4rem;flex-wrap:wrap}
.mh-panel {padding:1rem;min-height:100%;background:var(--bg)}
.mh-list {display:flex;flex-direction:column;border:1px solid var(--border);border-radius:var(--radius-md);overflow:clip}
.mh-row {display:flex;gap:.65rem;align-items:center;padding:.85rem;border:0;border-bottom:1px solid var(--border);background:transparent;color:var(--ink);text-align:left;font:inherit;width:100%;cursor:pointer}
.mh-row:last-child {border-bottom:0}.mh-row:hover {background:var(--surface-hover)}
.mh-row-main {flex:1;min-width:0}.mh-row-main strong {display:block;overflow-wrap:anywhere}
.mh-empty {padding:1.4rem;color:var(--muted);text-align:center}
.mh-form {display:flex;flex-direction:column;gap:1rem;min-width:0;border:0;margin:0;padding:0}
.mh-form label {display:flex;flex-direction:column;gap:.35rem}
.mh-form input,.mh-form select,.mh-form textarea {width:100%;min-width:0;border:1px solid var(--border-strong);border-radius:var(--radius-sm);padding:.55rem .65rem;background:var(--bg);color:var(--ink);font:inherit}
.mh-form select {padding-inline-end:2.3rem}.mh-form textarea {min-height:7rem;resize:vertical}
.mh-form:disabled {opacity:.65}.mh-columns {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}
.mh-form-hint {color:var(--muted);font-size:.8rem}
.mh-pre {white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font:inherit}
.mh-history {display:flex;flex-direction:column;gap:.75rem}
.mh-history-message {padding:.75rem;border:1px solid var(--border);border-radius:var(--radius-sm)}
.mh-history-message details {margin:.4rem 0}.mh-history-message summary {cursor:pointer;color:var(--muted)}
.mh-history-message[data-kind=agent_start] {background:var(--surface)}
.mh-footer {display:flex;gap:.5rem;align-items:center;justify-content:flex-end;width:100%;flex-wrap:wrap}
.mh-footer .mh-error {flex:1 1 100%}.mh-footer textarea {flex:1 1 100%;min-height:4rem;max-height:10rem;resize:vertical;padding:.6rem;border:1px solid var(--border-strong);border-radius:var(--radius-sm);background:var(--bg);color:var(--ink);font:inherit}
.mh-history-heading {position:static;display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
@media(max-width:600px){.mh-columns{grid-template-columns:1fr}.mh-panel{padding:.75rem}.mh-summary{margin:.5rem 0}.mh-row{padding:.7rem}.mh-button{min-height:2.25rem}}
`;
  document.head.append(node); return () => node.remove();
}
