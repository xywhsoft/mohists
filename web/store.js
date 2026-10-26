// One bound client and read subscription per owning conversation. Closing a
// view stops reads only; running operations belong to the native task group.
export function createStores({ delay = (fn, ms) => setTimeout(fn, ms), cancel = id => clearTimeout(id) } = {}) {
  const stores = new Map(); let disposed = false;
  const scope = sdk => {
    const c = sdk.context();
    return { project: c.project || c.projectId || "default", session: c.session || c.sessionId || "" };
  };
  function acquire(sdk) {
    if (disposed) throw Error("墨者界面已关闭");
    const context = scope(sdk), key = JSON.stringify(context);
    if (!context.session) throw Error("请先选择会话");
    let store = stores.get(key);
    if (!store) {
      const api = sdk.bind(context), abort = new AbortController(), listeners = new Set();
      const operations = new Set();
      let refs = 0, timer, pending, after = 0, epoch = "", last = "", busy = false;
      const state = { team: null, error: null, operationError: null, loading: true, busy: false };
      const emit = () => { for (const fn of listeners) fn(state); };
      const call = (action, params = {}, options = {}) => api.call("mohists.team", { action, ...params }, { signal: abort.signal, ...options });
      const refresh = async (reconcile = false) => {
        if (pending) return pending;
        pending = (async () => {
          try {
            state.team = await call(reconcile ? "refresh" : "get"); state.error = null;
          } catch (error) {
            if (error.code === "mohists_team_missing") { state.team = null; state.error = null; }
            else if (!abort.signal.aborted) state.error = error;
          } finally {
            pending = null; state.loading = false;
            if (!abort.signal.aborted) {
              const encoded = JSON.stringify(state);
              if (encoded !== last) { last = encoded; emit(); }
            }
          }
          return state;
        })(); return pending;
      };
      const poll = async () => {
        try {
          for (const id of operations) {
            const info = await api.wait(id, 0, { signal: abort.signal });
            if (info.terminal) {
              operations.delete(id);
              if (info.state !== "succeeded" || info.receipt_uncertain) state.operationError = Object.assign(
                Error(info.error?.message || "操作收据未确认，请查看任务状态后再决定"), { code: info.error?.code });
              if (!info.receipt_uncertain) await api.call("operation.release", { id }, { signal: abort.signal });
              await refresh(); emit();
            }
          }
          const events = await api.events({ after, ...(epoch ? { epoch } : {}), topic: "mohists.changed", limit: 128 }, { signal: abort.signal });
          after = events.cursor; epoch = events.epoch;
          if (events.resync_required || events.items.some(e => e.project === context.project && e.session === context.session)) await refresh();
        } catch (error) { if (!abort.signal.aborted) { state.error = error; emit(); } }
        finally { if (!abort.signal.aborted) timer = delay(poll, globalThis.document?.hidden ? 10000 : 1500); }
      };
      store = {
        context, api, state, call, refresh,
        retain() { refs++; },
        release() { if (--refs <= 0) { store.dispose(); stores.delete(key); } },
        subscribe(fn) { listeners.add(fn); fn(state); return () => listeners.delete(fn); },
        async mutate(action, params = {}, generation = state.team?.generation ?? 0) {
          if (busy) throw Error("请等待当前操作完成");
          busy = state.busy = true; emit();
          try { return await call(action, { ...params, expected_generation: generation }); }
          finally { busy = state.busy = false; await refresh(); emit(); }
        },
        async background(action, params, generation, operationId) {
          if (busy) throw Error("请等待当前操作完成");
          busy = state.busy = true; state.operationError = null; emit();
          try {
            const receipt = await api.start("mohists.team", { action, ...params, expected_generation: generation }, operationId, { signal: abort.signal });
            operations.add(receipt.id); return receipt;
          } finally { busy = state.busy = false; await refresh(); emit(); }
        },
        dispose() { abort.abort(); cancel(timer); listeners.clear(); },
      };
      stores.set(key, store); void refresh().then(() => { if (!abort.signal.aborted) void poll(); });
    }
    store.retain(); return store;
  }
  return { acquire, dispose() { disposed = true; for (const store of stores.values()) store.dispose(); stores.clear(); } };
}

export const roleName = role => ({ researcher: "研究员", worker: "执行者", reviewer: "复核者" })[role] || role;
export const stateName = state => ({ active: "协作中", queued: "待运行", starting: "启动中", running: "运行中", cancelling: "停止中",
  succeeded: "已完成", failed: "失败", cancelled: "已停止", stale: "约束已变化", requires_review: "需要确认",
  draining: "等待停止", revising: "更新约束中", completing: "正在结束", completed: "已结束", timed_out: "已超时", limited: "达到限制" })[state] || state;
export const terminal = state => ["succeeded", "failed", "cancelled", "stale", "timed_out", "limited"].includes(state);
export function groupChanged(store, generation) {
  if (store.state.team?.generation !== generation) throw Error("任务组已经变化。请关闭此窗口，重新选择当前成员。");
}
// Native event/run IDs can restart with the host. Only continuation chunks
// (positive exact byte offsets) may join a prior non-stream event.
export function historyFragment(event, previous) {
  const key = `${event.message_id}:${event.run_id}:${event.kind}:${event.kind === "model_text_delta" ? "stream" : event.source_event_id}`;
  const offset = event.text_offset || 0;
  return { key, end: offset + new TextEncoder().encode(event.text || "").length,
    join: previous?.key === key && (event.kind === "model_text_delta" || offset > 0 && previous.end === offset) };
}
