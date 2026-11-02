# 2026-11-03 Agent selection and execution entry

Mohists remains a main Agent supplied by an ordinary plugin. The host composer selector treats it like every other main-capable Agent. The dedicated sidebar task-creation menu and its unused creation module were removed.

Selecting or restoring an existing Mohists conversation opens its companion panel through `sdk.ui.registerAgent`. The callback is bound to the displayed conversation and releases its panel when that selection ends. A blank task records its Agent only when the first input creates the conversation. Selection alone makes no model request.

Device defaults are available under Settings → Extension settings → Mohists through `sdk.ui.registerSettingsPage`, with existing native validation, frozen fields during saving, and revision checks. Existing teams keep their settings and role bindings. Resolve or stop an active team before changing to another Agent; native member histories remain available.

The reported AVL task had a saved collaboration goal but zero main-chat events and no run. The previous Start action called only `mohists.team/start`; it never submitted the goal as a user message. Manual group creation is now explicitly named Save goal, states that it does not execute, and an unassigned group is labeled Awaiting assignments. The normal workflow is to select Mohists and send the goal from the main composer.

Verified in the sole existing project Home:

- Native profile switching preserves the populated conversation, model and permission, makes no model call itself, applies the coordinator role on the next input, and refuses running-runtime and SubAgent-only selections. Four loopback model calls; no vendor calls.
- The coordinator integration fixture completes both a direct simple reply without creating a team and the complete tools/member/multi-turn workflow.
- Browser interaction selected Mohists in a blank task, sent through the normal composer, received the deterministic local answer, and opened the companion panel automatically. Settings loaded and saved successfully; no console errors observed.
- Host regression covers callback cancellation and late cleanup, settings registration/removal, lost Agent-switch acknowledgements, per-project blank selections and stale replies after navigation. Mobile layout and the final packaged program are checked separately before local delivery.

This is a local candidate. No online publication or real vendor, Android hardware or cross-device acceptance is claimed.
