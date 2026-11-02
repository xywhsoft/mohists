import { test } from "node:test";
import assert from "node:assert/strict";
import { activate } from "../web/main.js";

test("Mohists uses the public Agent selector and settings page without creating a task or making a model request", async () => {
  const registrations = {}, calls = []; let closed = 0;
  globalThis.document = { createElement: () => ({ remove() {} }), head: { append() {} } };
  globalThis.matchMedia = () => ({ matches: false });
  const sdk = { ui: {
    registerPanel(id, value) { registrations[id] = value; },
    registerConversationAction(id, value) { registrations[id] = value; },
    registerConversationView(id, value) { registrations[id] = value; },
    registerAgent(id, value) { registrations[id] = value; },
    registerSettingsPage(id, value) { registrations[id] = value; },
    async openPanel(id) { calls.push(id); return { close() { closed++; } }; },
  } };
  const dispose = activate(sdk), agent = registrations["agent.mohists"];
  assert.ok(agent); assert.equal(registrations.mohists.title, "墨者");
  assert.equal(await agent.onSelected({ sdk, context: { session: "" }, signal: new AbortController().signal }), undefined);
  assert.deepEqual(calls, []);
  const cleanup = await agent.onSelected({ sdk, context: { session: "current" }, signal: new AbortController().signal });
  assert.deepEqual(calls, ["mohists.collaboration"]); cleanup(); assert.equal(closed, 1);
  await assert.rejects(agent.beforeDeselected({ context: { session: "current" }, sdk: { call: async () => ({ state: "active" }) } }), /先/);
  await agent.beforeDeselected({ context: { session: "current" }, sdk: { call: async () => ({ state: "completed" }) } });
  dispose();
});
