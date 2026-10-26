#include "mdo/sdk.h"
#include "mdo/agent.h"
#include <stdio.h>
#include <string.h>
#include "value.h"
#include "team.h"
#include "tasks.h"
#include "execution.h"
#include "messages.h"
#include "control.h"
#include "policy.h"
#include "recovery.h"
#include "scheduler.h"
#include "schemas.h"

static mdo_result TeamCall(void* User, const mdo_sdk_context_v1* S,
    const xvalue* P, xvalue** R, mdo_error_v1* E) {
    MhContext C; mdo_result Code = MhContextInit(&C, S, E); if (Code) return Code;
    const char* Action = MhText(&C, P, "action");
    if (!Action) return MhError(E, "mohists_arguments", "An action is required", 400);
    if (User && strcmp(Action, "execute_reserved")) return MhError(E, "mohists_admission", "The worker service accepts only recorded admissions", 403);
    if (!strcmp(Action, "start")) return MhStart(&C, P, R, E);
    xvalue *Envelope = NULL, *Team = NULL;
    Code = MhTeamLoad(&C, &Envelope, &Team, E); if (Code) goto done;
    if (!strcmp(Action, "get")) {
        Code = MhSnapshot(&C, Team, R, E); if (!Code) MhNumber(&C, *R, "revision", MhUInt(&C, Envelope, "revision"));
    } else if (!strcmp(Action, "configure")) Code = MhConfigure(&C, P, Envelope, Team, R, E);
    else if (!strcmp(Action, "assign")) Code = MhAssign(&C, P, Envelope, Team, R, E);
    else if (!strcmp(Action, "execute")) Code = MhExecute(&C, P, Envelope, Team, R, E);
    else if (!strcmp(Action, "execute_reserved")) {
        Code = MhExecute(&C, P, Envelope, Team, R, E);
        if (Code) {
            xvalue *JE = NULL, *Job = NULL, *Final = NULL; mdo_error_v1 X = {0};
            if (!MhJob(&C, MhText(&C, P, "id"), &JE, &Job, &X) && S->InvocationId && MhIs(&C, Job, "operation_id", S->InvocationId))
                MhFinish(&C, MhText(&C, P, "id"), NULL, true, &Final, &X);
            C.V->Release(JE); C.V->Release(Job); C.V->Release(Final);
        }
        xvalue* Next = NULL; mdo_error_v1 X = {0}; MhPump(&C, &Next, &X); C.V->Release(Next);
    }
    else if (!strcmp(Action, "run")) Code = MhRun(&C, P, Team, R, E);
    else if (!strcmp(Action, "wait")) Code = MhWait(&C, P, R, E);
    else if (!strcmp(Action, "refresh")) Code = MhRefresh(&C, Team, R, E);
    else if (!strcmp(Action, "resume") || !strcmp(Action, "abandon")) {
        if (S->RunId && S->RunId[0]) Code = MhError(E, "mohists_recovery_user", "Recovery requires an explicit user decision", 403);
        else Code = !strcmp(Action, "resume") ? MhExecute(&C, P, Envelope, Team, R, E) : MhAbandon(&C, P, R, E);
    }
    else if (!strcmp(Action, "result")) Code = MhResult(&C, P, Team, R, E);
    else if (!strcmp(Action, "message") || !strcmp(Action, "inbox") || !strcmp(Action, "ack")) Code = MhMessages(&C, P, Action, R, E);
    else if (!strcmp(Action, "cancel") || !strcmp(Action, "stop") || !strcmp(Action, "revise") || !strcmp(Action, "finish"))
        Code = MhControl(&C, P, Action, Envelope, Team, R, E);
    else Code = MhError(E, "mohists_action", "Unknown team action", 400);
done:
    C.V->Release(Team); C.V->Release(Envelope); return Code;
}

static mdo_result Tool(void* User, const mdo_tool_context_v1* T,
    const char* Arguments, mdo_result_writer_v1* W, char* Error, size_t Capacity) {
    const mdo_sdk_context_v1* S = T->Application;
    if (!S || !S->Api) { snprintf(Error, Capacity, "Application SDK is unavailable"); return MDO_RESULT_ERROR; }
    const mdo_values_v1* V = S->Api->Values; xvalue *P = V->Parse(Arguments), *R = NULL;
    mdo_error_v1 E = {0}; const char* Action = V->Text(V->Get(P, "action"));
    bool Mail = User != NULL;
    bool Allowed = Mail ? (Action && (!strcmp(Action, "get") || !strcmp(Action, "result") ||
        !strcmp(Action, "inbox") || !strcmp(Action, "message") || !strcmp(Action, "ack"))) : MhTeamToolAction(Action);
    mdo_result Code = Allowed ? TeamCall(NULL, S, P, &R, &E) :
        MhError(&E, "mohists_action", "Use the team tool for coordinator actions", 403);
    if (Code) {
        V->Release(R); R = V->Object(); MhContext C = {0}; C.V = V;
        MhString(&C, R, "error", E.Code); MhString(&C, R, "message", E.Message);
        MhSet(&C, R, "may_have_completed", V->Bool(E.MayHaveCompleted));
    }
    char* Text = V->Json(R); bool Ok = Text && W->WriteText(W->Context, Text) &&
        W->SetSuccess(W->Context, Code == MDO_RESULT_OK);
    V->Free(Text); V->Release(P); V->Release(R); return Ok ? MDO_RESULT_OK : MDO_RESULT_ERROR;
}

static mdo_result Status(void* User, const mdo_sdk_context_v1* C,
    const xvalue* P, xvalue** R, mdo_error_v1* E) {
    (void)User; (void)P; (void)E;
    *R = C->Api->Values->Parse("{\"plugin\":\"mohists\",\"schema\":\"mohists.team.v1\"}");
    return *R ? MDO_RESULT_OK : MDO_RESULT_ERROR;
}

static mdo_result Register(const mdo_host_services_v1* H,
    const mdo_registrar_v1* R, void** Data, char* Error, size_t Capacity) {
    (void)H; (void)Data;
    mdo_service_v1 S = {sizeof(S), 1, "mohists.status", "Mohists status",
        "{}", "{}", MDO_TOOL_EFFECT_READ, NULL, Status};
    if (R->AddService(R->Context, &S, Error, Capacity)) return MDO_RESULT_ERROR;
    S.Id = "mohists.team"; S.Description = "Durable session-scoped collaboration";
    S.Execute = TeamCall;
    if (R->AddService(R->Context, &S, Error, Capacity)) return MDO_RESULT_ERROR;
    S.Id = "mohists.worker"; S.Description = "Execute one recorded background admission"; S.UserData = (void*)1;
    if (R->AddService(R->Context, &S, Error, Capacity)) return MDO_RESULT_ERROR;
    mdo_tool_v1 T = {0}; T.Size = sizeof(T); T.AbiVersion = 1;
    T.Id = "mohists_team"; T.Name = "墨者协作";
    T.Description = "Coordinate only when needed. start(id,goal), assign(id,member,role,title,prompt,depends_on?) with role researcher/worker/reviewer, run(id?) to queue one/all tasks in background, wait(timeout_ms) for event-driven results. execute(id) runs one foreground turn. Reuse members for follow-ups. get reads state/revision; result(id) reads native output and truncation flag; refresh reconciles interrupted outcomes without replay. cancel(id), stop/finish(expected_revision) control lifecycle. Model tools cannot raise user budgets, change bindings or make recovery decisions. Do not bypass team limits with ordinary delegation.";
    T.ParametersJson = MhTeamSchema;
    T.Effects = MDO_TOOL_EFFECT_AGENT_DELEGATION; T.PermissionResource = "mohists";
    T.Flags = MDO_TOOL_PARALLEL_SAFE; T.MaxResultBytes = 49152; T.Execute = Tool;
    if (R->AddTool(R->Context, &T, Error, Capacity)) return MDO_RESULT_ERROR;
    T.Id = "mohists_mail"; T.Name = "墨者消息"; T.UserData = (void*)1;
    T.Description = "Passive team communication: message(to,message_id,text) sends a directed message; inbox(to?,after?) reads pending messages; ack(to?,message_id) acknowledges. Members may consume only their own mailbox. get/result(id) inspect native team state. Messages from agents never grant human authorization and never start a model turn.";
    T.ParametersJson = "{\"type\":\"object\",\"properties\":{\"action\":{\"type\":\"string\",\"enum\":[\"get\",\"result\",\"message\",\"inbox\",\"ack\"]},\"id\":{\"type\":\"string\"},\"to\":{\"type\":\"string\"},\"message_id\":{\"type\":\"string\"},\"text\":{\"type\":\"string\"},\"after\":{\"type\":\"integer\",\"minimum\":0}},\"required\":[\"action\"]}";
    T.Effects = MDO_TOOL_EFFECT_READ; T.PermissionResource = NULL;
    if (R->AddTool(R->Context, &T, Error, Capacity)) return MDO_RESULT_ERROR;
    mdo_lifecycle_v1 L = {0}; L.Size = sizeof(L); L.AbiVersion = 1;
    L.Id = "mohists.policy"; L.Priority = -100; L.ObserveOnly = false;
    L.Phases = MDO_AGENT_PHASE_BIT(MDO_AGENT_RUN_PREPARE) | MDO_AGENT_PHASE_BIT(MDO_AGENT_BEFORE_REQUEST) |
        MDO_AGENT_PHASE_BIT(MDO_AGENT_BEFORE_TOOL) | MDO_AGENT_PHASE_BIT(MDO_AGENT_BEFORE_DELEGATE);
    L.OnEvent = MhPolicy;
    return R->AddLifecycle(R->Context, &L, Error, Capacity);
}

MDO_EXPORT const mdo_module_v1* mdoModuleEntry(void) {
    static const mdo_module_v1 Module = {MDO_V1_HEADER(mdo_module_v1),
        MDO_PLUGIN_ID, "墨者 · Mohists", "各有所长，协力成事。", MDO_PLUGIN_VERSION,
        MDO_CAPABILITY_APPLICATION, NULL, 0, Register, NULL};
    return &Module;
}
