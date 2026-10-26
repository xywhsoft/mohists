import { test } from "node:test";
import assert from "node:assert/strict";
import { createStores, groupChanged, historyFragment } from "../web/store.js";

const flush = async () => { for (let n = 0; n < 8; n++) await Promise.resolve(); };
function fixture() {
  const calls = [], timers = [], cancelled = []; let team = { generation: 1, state: "active", jobs: [] }, events = [];
  const bound = { async call(method, params, options) {
    calls.push({ method, params, options });
    if (params.action === "get") return team;
    return { accepted: true };
  }, async events(params, options) { calls.push({ method: "events.read", params, options }); return { cursor: 4, epoch: "a", items: events }; } };
  const sdk = { context: () => ({ project: "mohists", session: "owner" }), bind(context) { bound.context = context; return bound; } };
  const pool = createStores({ delay(fn) { timers.push(fn); return fn; }, cancel(fn) { cancelled.push(fn); } });
  return { pool, sdk, bound, calls, timers, cancelled, setTeam: v => { team = v; }, setEvents: v => { events = v; } };
}

test("shared read lifecycle is fixed to one session; closing all views never cancels work", async () => {
  const f = fixture(), a = f.pool.acquire(f.sdk), b = f.pool.acquire(f.sdk);
  assert.equal(a, b); assert.deepEqual(a.context, { project: "mohists", session: "owner" });
  await flush(); assert.equal(f.calls.filter(c => c.params.action === "get").length, 1);
  let seen; const unsub = a.subscribe(s => { seen = s.team; }); assert.equal(seen.generation, 1);
  await a.mutate("cancel", { id: "x" });
  assert.deepEqual(f.calls.find(c => c.params.action === "cancel").params, { action: "cancel", id: "x", expected_generation: 1 });
  const abort = f.calls[0].options.signal;
  a.release(); assert.equal(abort.aborted, false); b.release(); assert.equal(abort.aborted, true);
  assert.equal(f.calls.some(c => c.method === "operation.cancel"), false); unsub(); f.pool.dispose();
});

test("unrelated session events do not reload; owned changes reload and stale generation is rejected", async () => {
  const f = fixture(), s = f.pool.acquire(f.sdk); await flush();
  const before = f.calls.length; f.setEvents([{ project: "other", session: "owner" }]);
  await f.timers.shift()();
  assert.equal(f.calls.length, before + 1);
  f.setTeam({ generation: 2, state: "active", jobs: [] });
  f.setEvents([{ project: "mohists", session: "owner" }]); await f.timers.shift()();
  assert.equal(s.state.team.generation, 2); assert.throws(() => groupChanged(s, 1), /任务组已经变化/);
  s.release(); f.pool.dispose();
});

test("stopped plugin refuses new stores and disposes ongoing subscriptions", async () => {
  const f = fixture(), s = f.pool.acquire(f.sdk); await flush();
  let count = 0; s.subscribe(() => count++); const before = count; f.pool.dispose();
  assert.throws(() => f.pool.acquire(f.sdk), /界面已关闭/);
  assert.equal(f.calls[0].options.signal.aborted, true); assert.equal(count, before);
});

test("explicit background decisions keep their ID and surface an asynchronous failure without replay", async () => {
  const f = fixture(); let starts = 0;
  f.bound.start = async (method, params, id) => { starts++; assert.equal(method, "mohists.team"); assert.equal(params.expected_generation, 1); return { id }; };
  f.bound.wait = async id => ({ id, terminal: true, state: "failed", error: { code: "mohists_conflict", message: "Native decision changed" } });
  const s = f.pool.acquire(f.sdk); await flush();
  await s.background("resume", { id: "job" }, 1, "sdk-recorded-intent");
  await f.timers.shift()();
  assert.equal(starts, 1); assert.equal(s.state.operationError.code, "mohists_conflict");
  assert.deepEqual(f.calls.find(c => c.method === "operation.release").params, { id: "sdk-recorded-intent" });
  await s.refresh(); assert.equal(s.state.operationError.message, "Native decision changed");
  await f.timers.shift()(); assert.equal(starts, 1); s.release();
});

test("restarted native IDs cannot merge a new start into the previous user input", () => {
  const event = { message_id: "task.one", run_id: 1, kind: "agent_start", source_event_id: 1, text_offset: 0, text: "原始🙂" };
  const first = historyFragment(event);
  assert.equal(historyFragment({ ...event, text: "Resuming interrupted run" }, first).join, false);
  assert.equal(historyFragment({ ...event, text_offset: first.end, text: "续片段" }, first).join, true);
  assert.equal(historyFragment({ ...event, text_offset: first.end - 1 }, first).join, false);
  const delta = { ...event, kind: "model_text_delta" };
  assert.equal(historyFragment({ ...delta, source_event_id: 2 }, historyFragment(delta)).join, true);
});
