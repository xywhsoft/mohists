import { createStores } from "./store.js";
import { installStyles } from "./styles.js";
import { mountPanel, mountSummary, openMember } from "./views.js";

export function activate(sdk) {
  const stores = createStores(), removeStyles = installStyles();
  const eligible = async ({ sdk, context, signal }) => {
    const session = await sdk.call("session.get", { path: { project: context.project, session: context.session } }, { signal });
    if (session.data.agent_id === "agent.mohists") return true;
    try { await sdk.call("mohists.team", { action: "get" }, { signal }); return true; }
    catch (e) { if (e.code === "mohists_team_missing") return false; throw e; }
  };
  const open = async bound => {
    if (globalThis.matchMedia("(max-width: 760px)").matches) {
      bound.ui.layers.open({ title: "墨者协作", icon: "branch", width: "92%", height: "88%", mobile: "fullscreen",
        render(root, { layer }) {
          const store = stores.acquire(bound), dispose = mountPanel(root, { sdk: bound, store, openMember });
          const close = document.createElement("button"); close.className = "mh-button"; close.textContent = "关闭";
          close.onclick = () => layer.close(); layer.footer.append(close);
          return () => { dispose(); store.release(); };
        } });
    } else await bound.ui.openPanel("mohists.collaboration");
  };
  sdk.ui.registerPanel("mohists.collaboration", { title: "墨者协作", placement: "right", scope: "session",
    mount(root, { sdk, signal }) {
      const store = stores.acquire(sdk), dispose = mountPanel(root, { sdk, store, openMember });
      return () => { dispose(); store.release(); };
    } });
  sdk.ui.registerConversationAction("mohists.open", { label: "墨者协作", icon: "branch", when: eligible,
    execute: ({ sdk }) => open(sdk) });
  sdk.ui.registerConversationView("mohists.summary", { when: eligible,
    mount(root, { sdk }) {
      const store = stores.acquire(sdk), dispose = mountSummary(root, { sdk, store, openPanel: () => open(sdk) });
      return () => { dispose(); store.release(); };
    } });
  return () => { stores.dispose(); removeStyles(); };
}
