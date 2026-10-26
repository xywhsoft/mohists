import { roleName, stateName, terminal, groupChanged, historyFragment } from "./store.js";

const el = (tag, cls = "", text) => { const n = document.createElement(tag); n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const append = (root, ...nodes) => { root.append(...nodes); return root; };
const tag = state => { const n = el("span", "mh-tag", stateName(state)); n.dataset.state = state; return n; };
const errorText = error => `${error.message || error}${error.code ? ` (${error.code})` : ""}`;
function button(label, fn, cls = "") {
  const b = el("button", `mh-button ${cls}`, label); b.type = "button"; b.onclick = fn; return b;
}
function field(form, label, type = "text", value = "") {
  const n = el(type === "textarea" ? "textarea" : type === "select" ? "select" : "input");
  if (n.tagName === "INPUT") n.type = type;
  n.value = value; append(form, append(el("label", "", label), n)); return n;
}
function selectOptions(select, items, value) {
  for (const [id, label] of items) { const option = el("option", "", label); option.value = id; select.append(option); }
  select.value = value || items[0]?.[0] || "";
}
const id = prefix => `${prefix}-${crypto.randomUUID().replaceAll("-", "").slice(0, 24)}`;
function windowForm(sdk, { title, width = "42rem", render, submit, save = "保存", store }) {
  let posting = false;
  store?.retain();
  return sdk.ui.layers.open({ title, icon: "branch", width, height: "auto", mobile: "fullscreen",
    onClosed: () => store?.release(),
    beforeClose: () => !posting,
    render(root, { layer, signal }) {
      root.classList.add("mh"); layer.footer.classList.add("mh");
      const form = el("form"), fields = el("fieldset", "mh-form"), error = el("p", "mh-error");
      form.append(fields); root.append(form); const read = render(fields, { signal });
      const cancel = button("取消", () => layer.close()), accept = button(save, () => form.requestSubmit(), "mh-primary");
      layer.footer.append(append(el("div", "mh-footer"), error, cancel, accept));
      form.onsubmit = async event => {
        event.preventDefault(); if (posting) return;
        posting = true; fields.disabled = accept.disabled = cancel.disabled = true; error.textContent = "";
        try { await submit(read(), { signal }); posting = false; await layer.close("saved"); }
        catch (e) { if (!signal.aborted) error.textContent = errorText(e); }
        finally { posting = false; fields.disabled = accept.disabled = cancel.disabled = false; }
      };
    } });
}

export function openAssignment(sdk, store, member) {
  const team = store.state.team, generation = team.generation, taskId = id("task");
  return windowForm(sdk, { store, title: member ? `指导 ${member.member}` : "分派任务", save: "分派并运行",
    render(root) {
      const title = field(root, "任务名称"); title.required = true; title.maxLength = 160;
      const role = field(root, "角色", "select"); selectOptions(role, ["researcher", "worker", "reviewer"].map(r => [r, roleName(r)]), member?.role);
      const who = field(root, "成员标识", "text", member?.member || id("member")); who.required = true; who.pattern = "[A-Za-z0-9_.-]{1,48}"; who.maxLength = 48;
      if (member) role.disabled = who.readOnly = true;
      const prompt = field(root, "任务或指导内容", "textarea"); prompt.required = true;
      root.append(el("p", "mh-form-hint", member ? "沿用此成员的真实上下文。已有任务运行时，新任务排队；不会暗中打断或重放。" : "研究与复核只读。执行成员沿用当前会话权限，最多一个成员写入。"));
      return () => ({ id: taskId, title: title.value.trim(), role: role.value, member: who.value, prompt: prompt.value });
    },
    async submit(params) {
      groupChanged(store, generation);
      await store.mutate("assign", params, generation);
      await store.mutate("run", { id: taskId }, generation);
    } });
}

export function openTeamConfig(sdk, store) {
  const team = store.state.team, generation = team.generation, revision = team.revision;
  return windowForm(sdk, { store, title: "本次协作设置", render(root) {
    const cols = el("div", "mh-columns"); root.append(cols);
    const concurrency = field(cols, "同时运行的成员", "number", team.concurrency); concurrency.min = "1"; concurrency.max = "3";
    const calls = field(cols, "累计成员轮次上限", "number", team.max_calls); calls.min = "1"; calls.max = "128";
    const roles = {};
    for (const r of ["researcher", "worker", "reviewer"]) {
      root.append(el("h4", "", roleName(r))); const group = el("div", "mh-columns"); root.append(group);
      const agent = field(group, "Agent / SubAgent 标识", "text", team.roles[r].agent_id); agent.required = true;
      const model = field(group, "模型标识（留空沿用会话）", "text", team.roles[r].model_id); roles[r] = [agent, model];
    }
    root.append(el("p", "mh-form-hint", "仅在分派任务前设置。已创建成员的角色和模型绑定保持固定；自定义研究和复核角色同样只读。"));
    return () => ({ expected_revision: revision, concurrency: Number(concurrency.value), max_calls: Number(calls.value),
      roles: Object.fromEntries(Object.entries(roles).map(([r, [a, m]]) => [r, { agent_id: a.value.trim(), model_id: m.value.trim() }])) });
  }, async submit(params) { groupChanged(store, generation); await store.mutate("configure", params, generation); } });
}

export function openStart(sdk, store) {
  const generation = store.state.team?.generation ?? 0, groupId = id("team");
  return windowForm(sdk, { store, title: "开始协作", save: "开始", render(root) {
    const goal = field(root, "协作目标", "textarea"); goal.required = true;
    root.append(el("p", "mh-form-hint", "简单任务可直接在主对话完成；复杂任务再分派给成员。"));
    return () => ({ id: groupId, goal: goal.value });
  }, submit: p => store.mutate("start", p, generation) });
}

export function mountSummary(root, { sdk, store, openPanel }) {
  root.classList.add("mh");
  return store.subscribe(({ team, error, operationError }) => {
    root.replaceChildren(); if (!team && !error) return;
    const box = el("div", "mh-summary"); root.append(box);
    if (error) { box.append(el("p", "mh-error", errorText(error)), button("重新读取", () => store.refresh())); return; }
    box.append(append(el("div", "mh-line"), el("strong", "mh-grow", "墨者 · 分工协作"), tag(team.state), button("查看分工", openPanel)));
    box.append(el("p", "mh-muted", team.goal)); const jobs = el("div", "mh-summary-jobs"); box.append(jobs);
    if (operationError) box.append(el("p", "mh-error", errorText(operationError)));
    const counts = new Map(); for (const job of team.assignment_items) counts.set(job.state, (counts.get(job.state) || 0) + 1);
    for (const [state, count] of counts) jobs.append(el("span", "mh-tag", `${stateName(state)} ${count}`));
    if (!counts.size) jobs.append(el("span", "mh-muted", "尚未分派成员，协调者可直接处理。"));
  });
}

export function mountPanel(root, { sdk, store, openMember }) {
  root.classList.add("mh", "mh-panel"); let error = "";
  const perform = async fn => { try { error = ""; await fn(); } catch (e) { error = errorText(e); } render(store.state); };
  const render = ({ team, loading, busy, error: network, operationError }) => {
    root.replaceChildren(); const box = el("div", "mh-stack"); root.append(box);
    const actions = el("div", "mh-line"); box.append(append(actions, el("h3", "mh-grow", "墨者协作"), button("刷新", () => perform(() => store.refresh(true)))));
    if (network || error) box.append(el("p", "mh-error", network ? errorText(network) : error));
    if (operationError) box.append(el("p", "mh-error", errorText(operationError)));
    if (loading) { box.append(el("p", "mh-empty", "正在读取…")); return; }
    if (!team) { box.append(el("p", "mh-muted", "按需分工，成员独立保留上下文。"), button("开始协作", () => openStart(sdk, store), "mh-primary")); return; }
    box.append(append(el("div", "mh-line"), tag(team.state), el("span", "mh-muted", `成员轮次 ${team.calls_used} / ${team.max_calls} · 并行上限 ${team.concurrency}`)));
    box.append(el("p", "", team.goal));
    const operations = el("div", "mh-line"); box.append(operations);
    if (team.state === "active") {
      operations.append(button("分派任务", () => openAssignment(sdk, store), "mh-primary"));
      if (!team.jobs.length) operations.append(button("协作设置", () => openTeamConfig(sdk, store)));
      if (team.assignment_items.some(j => j.state === "queued")) operations.append(button("运行排队任务", () => perform(() => store.mutate("run"))));
      operations.append(button("停止全部", () => perform(() => store.mutate("stop", { expected_revision: team.revision })), "mh-danger"));
      if (!team.active.length) operations.append(button("结束协作", () => perform(() => store.mutate("finish", { expected_revision: team.revision }))));
    } else if (["cancelled", "completed"].includes(team.state)) operations.append(button("开始新协作", () => openStart(sdk, store)));
    const list = el("div", "mh-list"); box.append(list);
    if (!team.assignment_items.length) list.append(el("p", "mh-empty", "尚未分派任务"));
    for (const job of team.assignment_items) {
      const row = button("", () => openMember(sdk, store, job, team.generation)); row.className = "mh-row";
      row.append(append(el("div", "mh-row-main"), el("strong", "", job.title), el("span", "mh-muted", `${roleName(job.role)} · ${job.member}`)), tag(job.state)); list.append(row);
    }
    box.append(el("p", "mh-muted", "点击任务查看真实成员会话。关闭面板不会停止运行；修改或停止任务请使用明确的操作。"));
    for (const b of operations.querySelectorAll("button")) b.disabled = busy;
  };
  return store.subscribe(render);
}

export function openMember(sdk, store, job, generation) {
  store.retain();
  const window = sdk.ui.layers.open({ title: `${roleName(job.role)} · ${job.member}`, icon: "branch", width: "64rem", height: "85%", mobile: "fullscreen",
    render(root, { layer, signal }) {
      root.classList.add("mh"); layer.footer.classList.add("mh");
      const box = el("div", "mh-stack"), status = el("div", "mh-line"), history = el("div", "mh-history"), notice = el("p", "mh-muted"), fault = el("p", "mh-error");
      const outcomeError = el("p", "mh-error");
      root.append(box); box.append(status, el("h3", "", job.title), outcomeError, notice, history);
      const more = button("加载更多记录", () => void read()); box.append(more);
      const guide = button("指导成员", () => openAssignment(sdk, store, job), "mh-primary");
      const stop = button("停止任务", () => void action(() => store.mutate("cancel", { id: job.id }, generation)), "mh-danger");
      const recover = button("处理中断", () => openRecovery(sdk, store, job, generation)); recover.hidden = true;
      layer.footer.append(append(el("div", "mh-footer"), fault, guide, recover, stop, button("关闭", () => layer.close())));
      let cursor = 0, reading = false, timer, groupStale = false, lastMessage, empty;
      const streamed = new Set();
      const started = new Set();
      const action = async fn => { try { fault.textContent = ""; groupChanged(store, generation); await fn(); } catch (e) { fault.textContent = errorText(e); } };
      const read = async () => {
        if (reading || signal.aborted) return; reading = true; more.disabled = true;
        try {
          const page = await store.call("history", { member: job.member, generation, after: cursor, limit: 32 }, { signal });
          if (signal.aborted) return;
          notice.textContent = !page.available ? "此成员尚未保存可见历史。" : !page.complete_from_creation ? "早期运行未启用可见历史，以下为已有记录。" : "展示实际输入、可见回复与工具记录；不展示隐藏推理。";
          for (const event of page.items) {
            empty?.remove(); empty = null;
            if (["model_text_delta", "agent_start", "tool_start", "tool_done", "error", "recovery_required", "recovery_resolved", "artifact_created", "agent_done"].includes(event.kind)) {
              const run = `${event.message_id}:${event.run_id}`;
              if (event.kind === "agent_start" && !event.text_offset) streamed.delete(run);
              if (event.kind === "model_text_delta") streamed.add(run);
              if (event.kind === "agent_done" && streamed.has(run)) continue;
              const fragment = historyFragment(event, lastMessage);
              if (fragment.join) {
                lastMessage.text.append(document.createTextNode(event.text)); lastMessage.end = fragment.end; continue;
              }
              const entry = el("article", "mh-history-message"); entry.dataset.kind = event.kind;
              const source = event.source === "user" ? "用户指导" : event.source === "agent" ? "协调者委派 / Agent 消息" : "成员";
              let text;
              if (event.kind.startsWith("tool_")) {
                const detail = el("details"); detail.append(el("summary", "", `${event.tool_name || "工具"} · ${event.kind === "tool_start" ? "调用" : event.success ? "成功" : "失败"}`));
                text = el("pre", "mh-pre", event.text); detail.append(text); entry.append(detail);
              } else {
                const headings = { error: "运行错误", recovery_required: "中断待确认", recovery_resolved: "已处理恢复决策", artifact_created: "产物" };
                const inputLabel = started.has(event.message_id) ? "继续本轮" : source;
                if (event.kind === "agent_start") started.add(event.message_id);
                entry.append(el("p", "mh-muted", event.kind === "agent_start" ? inputLabel : ["model_text_delta", "agent_done"].includes(event.kind) ? "成员回复" : headings[event.kind] || event.kind));
                text = el("div", "mh-pre", event.text || stateName(event.outcome || "")); entry.append(text);
              }
              if (event.source_truncated) entry.append(el("p", "mh-muted", "原始事件内容已截短，请查看相关产物。"));
              if (event.artifact_path) entry.append(el("p", "mh-muted", `产物：${event.artifact_path}`));
              history.append(entry); lastMessage = { ...fragment, text };
            }
          }
          cursor = page.next_cursor; more.hidden = !page.has_more; more.textContent = "加载更多记录";
          if (!history.childNodes.length) { empty = el("p", "mh-empty", "尚无可见记录"); history.append(empty); }
        } catch (e) { if (!signal.aborted) { fault.textContent = errorText(e); more.hidden = false; more.textContent = "重新读取记录"; } }
        finally { reading = false; more.disabled = false; }
      };
      const unsub = store.subscribe(state => {
        const current = state.team?.assignment_items?.find(j => j.id === job.id);
        groupStale = state.team?.generation !== generation;
        status.replaceChildren(tag(groupStale ? job.state : current?.state || job.state), el("span", "mh-muted", `任务组 ${generation} · ${job.agent_id}`));
        outcomeError.textContent = (groupStale ? job.error : current?.error) || "";
        guide.disabled = state.busy || groupStale || state.team?.state !== "active";
        stop.disabled = state.busy || groupStale || terminal(current?.state || job.state);
        recover.hidden = groupStale || (current?.state || job.state) !== "requires_review";
        recover.disabled = state.busy;
        if (groupStale) notice.textContent = "当前展示之前任务组的记录，不能操作新任务组。";
      });
      const poll = async () => { await read(); if (!signal.aborted) timer = setTimeout(poll, document.hidden ? 10000 : 1800); };
      void poll();
      return () => { clearTimeout(timer); unsub(); store.release(); };
    } });
  return window;
}

export function openRecovery(sdk, store, job, generation) {
  store.retain(); let posting = false;
  const operationId = `sdk-${crypto.randomUUID().replaceAll("-", "")}`;
  return sdk.ui.layers.open({ title: "处理中断 · 明确恢复决策", icon: "branch", width: "56rem", height: "80%", mobile: "fullscreen",
    beforeClose: () => !posting,
    onClosed: () => store.release(),
    render(root, { layer, signal }) {
      root.classList.add("mh"); layer.footer.classList.add("mh");
      const form = el("fieldset", "mh-form"), fault = el("p", "mh-error"); root.append(form);
      const retry = button("重新查看", () => void load()), cancel = button("关闭", () => layer.close());
      const resume = button("继续此轮", () => void act(false), "mh-primary");
      const abandon = button("放弃此轮", () => void act(true), "mh-danger");
      layer.footer.append(append(el("div", "mh-footer"), fault, retry, abandon, resume, cancel));
      let view, choices = [];
      const update = () => {
        const stale = store.state.team?.generation !== generation;
        const active = store.state.team?.state === "active";
        form.disabled = posting;
        abandon.disabled = posting || !view || stale || view.state !== "requires_review";
        resume.disabled = posting || !view || stale || !active || !view.recovery.available || view.state !== "requires_review" ||
          choices.some(([, select]) => !select.value) || store.state.team.calls_used >= store.state.team.max_calls;
        retry.disabled = cancel.disabled = posting;
      };
      const load = async () => {
        view = null; choices = []; form.replaceChildren(el("p", "mh-muted", "正在读取原生恢复信息…")); fault.textContent = ""; update();
        try {
          const result = await store.call("recovery", { id: job.id, expected_generation: generation }, { signal });
          if (signal.aborted) return; groupChanged(store, generation); view = result;
          form.replaceChildren(el("h3", "", job.title), el("p", "mh-form-hint", "上次运行中断，没有自动重放。请核对工具是否已经生效，再决定继续或放弃。放弃会保留未知结果，并不会撤销已经发生的操作。"));
          if (view.error) form.append(el("p", "mh-error", view.error));
          if (!view.recovery.available) form.append(el("p", "mh-error", "没有可读取的原生账本，无法安全继续。可明确放弃此轮后分派新任务。"));
          if (!view.recovery.items.length) form.append(el("p", "mh-muted", "账本中没有未决工具调用。继续将从已保存的模型上下文恢复，可能重新发起上次未完成的模型请求。"));
          for (const item of view.recovery.items) {
            const card = el("div", "mh-card mh-stack"); form.append(card);
            card.append(append(el("div", "mh-line"), el("strong", "mh-grow", item.tool), el("span", "mh-tag", item.automatic_retry_safe ? "可安全重试" : "可能已有副作用")));
            const detail = el("details"); detail.append(el("summary", "", "查看原始参数"), el("pre", "mh-pre", item.arguments_json)); card.append(detail);
            const select = field(card, "此工具的处理方式", "select");
            selectOptions(select, [["", "请选择，不会自动执行"], ["record_uncertain", "不重试，记录为结果未知"], ...(item.available ? [["retry", "明确重新执行此工具"]] : [])], "");
            select.onchange = update; choices.push([item.tool_call_id, select]);
          }
        } catch (error) { if (!signal.aborted) { fault.textContent = errorText(error); form.replaceChildren(); } }
        finally { update(); }
      };
      const act = async abandoning => {
        if (posting || !view) return; posting = true; fault.textContent = ""; update();
        try {
          groupChanged(store, generation);
          const params = { id: job.id, expected_revision: view.revision, expected_member_revision: view.member_state.revision };
          if (abandoning) await store.mutate("abandon", params, generation);
          else await store.background("resume", { ...params, expected_recovery_token: view.recovery.recovery_token,
            decisions: choices.map(([tool_call_id, select]) => ({ tool_call_id, action: select.value })) }, generation, operationId);
          posting = false; await layer.close("submitted");
        } catch (error) { if (!signal.aborted) fault.textContent = errorText(error); }
        finally { posting = false; update(); }
      };
      const unsubscribe = store.subscribe(update); void load();
      return unsubscribe;
    } });
}
