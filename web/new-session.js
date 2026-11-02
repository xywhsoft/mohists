/* Create an explicit Mohists conversation without changing global defaults.
 * Retain uncertain creation intent so a retry cannot create duplicate tasks. */
export function createNewMohistsTask(sdk, newId = () => crypto.randomUUID().replaceAll("-", "")) {
  let busy = false, pending = null;
  return async () => {
    if (busy) return;
    busy = true;
    try {
      const context = sdk.context(), project = context.projectId || "default";
      if (!pending || pending.project !== project) pending = { project, id: newId() };
      const intent = pending;
      const api = sdk.bind({ project, session: "" });
      if (!intent.session) {
        const response = await api.call("session.create", { body: {
          project_id: project, client_session_id: intent.id,
          title: "墨者协作", agent_id: "agent.mohists",
        } });
        if (!response?.data?.id) throw Error("未能确认墨者会话，请重试。");
        intent.session = response.data.id;
      }
      const current = sdk.context();
      if ((current.projectId || "default") !== project || current.sessionId !== context.sessionId)
        throw Error("墨者会话已创建。当前页面已切换，请从会话列表打开，或再次点击新建墨者任务。");
      await sdk.call("ui.invoke", { client: sdk.clientId, action: "ui.navigate",
        params: { project, session: intent.session } });
      pending = null;
    } finally { busy = false; }
  };
}
