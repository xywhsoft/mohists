# 2026-11-03 final local delivery

The Agent-selection update was installed in `E:\software\mdo` for user testing. It has not been published to the store. Plugin version remains 0.1.0; the compatible Windows client remains 0.8.5.

## Use

1. In a new or idle conversation, use the Agent selector to the right of the permission control and choose 墨者.
2. Send the goal from the main conversation input. The coordinator can answer directly or delegate work as needed. Selecting the Agent or manually saving a team goal does not start a model run.
3. The collaboration panel opens automatically and shows assignments and member conversations. Closing the panel does not stop work; use its explicit stop/end actions. Resolve an active team before switching to a different Agent.
4. Change device defaults under 设置 → 扩展设置 → 墨者. Existing teams retain their settings and bindings.

The old AVL attempt saved a goal without submitting any main-chat event. Its goal remains intact and its state now correctly says 待分工. The user can submit that requirement through the main input; acceptance did not submit it or call a real vendor.

## Evidence

- Source implementation: `4834fa0`, `e4ab70a`; compatible host implementation: `dc0e7ee3`, `cc4198e5`, `e2c55cce`.
- Final ZIP: 74,918 bytes; SHA-256 `bc8ca3ba03635f1ff30e6c8454c2eb9d5c0dbf316099b4478c1468350b8adf68`. All 30 packaged files match the installed directory.
- Final GUI executable: 6,670,706 bytes; SHA-256 `f40b7205f7df68196962ce988bab96dc31ab0516ed3439fb510515e3a5272330`; PE GUI subsystem 2. The extra console seen in an intermediate candidate was corrected before delivery.
- Native accessibility verification confirmed the selected Mohists Agent, intact goal, dynamic input prompt and automatically opened companion panel. Account remained signed in. The user program was reopened and left running.
- Local fixture integration and browser tests passed execution through the main composer, populated-history Agent switching, busy-runtime refusal, settings save and callback cleanup. Desktop and 360-pixel-wide layouts passed. Seven plugin frontend tests, 56 targeted host Node tests, 19 frontend contracts and 11 SDK contracts passed. No real vendor, Android hardware or cross-device result is claimed.

Screenshot of the installed service: `runtime/acceptance/agent-selection-installed-browser.png`. Desktop/narrow fixture screenshots and private receipts are retained in the project runtime and host build folders. The existing user executable and plugin were backed up under `E:\software\mdo\mdo-home\data\backups\mohists-agent-selection-20261103`.
