#include "mdo/sdk.h"
#include <stdio.h>
#include <string.h>
#include "value.h"
#include "team.h"
#include "tasks.h"

static mdo_result TeamCall(void* User, const mdo_sdk_context_v1* S,
    const xvalue* P, xvalue** R, mdo_error_v1* E) {
    (void)User; MhContext C; mdo_result Code = MhContextInit(&C, S, E); if (Code) return Code;
    const char* Action = MhText(&C, P, "action");
    if (!Action) return MhError(E, "mohists_arguments", "An action is required", 400);
    if (!strcmp(Action, "start")) return MhStart(&C, P, R, E);
    xvalue *Envelope = NULL, *Team = NULL;
    Code = MhTeamLoad(&C, &Envelope, &Team, E); if (Code) goto done;
    if (!strcmp(Action, "get")) {
        Code = MhSnapshot(&C, Team, R, E); if (!Code) MhNumber(&C, *R, "revision", MhUInt(&C, Envelope, "revision"));
    } else if (!strcmp(Action, "configure")) Code = MhConfigure(&C, P, Envelope, Team, R, E);
    else if (!strcmp(Action, "assign")) Code = MhAssign(&C, P, Envelope, Team, R, E);
    else Code = MhError(E, "mohists_action", "Unknown team action", 400);
done:
    C.V->Release(Team); C.V->Release(Envelope); return Code;
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
    return R->AddService(R->Context, &S, Error, Capacity);
}

MDO_EXPORT const mdo_module_v1* mdoModuleEntry(void) {
    static const mdo_module_v1 Module = {MDO_V1_HEADER(mdo_module_v1),
        MDO_PLUGIN_ID, "墨者 · Mohists", "各有所长，协力成事。", MDO_PLUGIN_VERSION,
        MDO_CAPABILITY_APPLICATION, NULL, 0, Register, NULL};
    return &Module;
}
