#ifndef MOHISTS_TEAM_H
#define MOHISTS_TEAM_H

static const char* MhRoles[] = {"researcher", "worker", "reviewer"};
static const char* MhAgents[] = {"subagent.mohists-researcher", "subagent.mohists-worker", "subagent.mohists-reviewer"};
static int MhRole(const char* S) {
    for (int I = 0; I < 3; ++I) if (S && !strcmp(S, MhRoles[I])) return I;
    return -1;
}
static mdo_result MhStart(MhContext* C, const xvalue* P, xvalue** R, mdo_error_v1* E) {
    if (MhCoordinator(C, E)) return MDO_RESULT_ERROR;
    const char* Id = MhText(C, P, "id"), *Goal = MhText(C, P, "goal");
    if (!MhId(Id, 64) || !Goal || !Goal[0] || strlen(Goal) > 4096)
        return MhError(E, "mohists_arguments", "Supply a portable id and a goal of 1..4096 UTF-8 bytes", 400);
    xvalue* Old = NULL; mdo_result Code = MhLoad(C, "team", &Old, E); if (Code) return Code;
    const xvalue* Previous = C->V->Get(Old, "value");
    if (MhIs(C, Previous, "id", Id)) {
        if (!MhIs(C, Previous, "goal", Goal)) Code = MhError(E, "mohists_identity_conflict", "Group id already has another goal", 409);
        else *R = C->V->Clone(Previous);
        C->V->Release(Old); return Code;
    }
    if (Previous && !MhIs(C, Previous, "state", "completed") && !MhIs(C, Previous, "state", "cancelled")) {
        C->V->Release(Old); return MhError(E, "mohists_team_open", "Finish or stop the previous group before starting another", 409);
    }
    xvalue* Team = C->V->Parse("{\"schema\":\"mohists.team.v1\",\"state\":\"active\",\"constraint_revision\":1,\"concurrency\":3,\"max_calls\":24,\"calls_used\":0,\"jobs\":[],\"active\":[],\"speaker\":\"coordinator\"}");
    MhString(C, Team, "id", Id); MhString(C, Team, "goal", Goal);
    MhNumber(C, Team, "generation", MhUInt(C, Previous, "generation") + 1);
    xvalue* Bindings = C->V->Object();
    for (int I = 0; I < 3; ++I) {
        xvalue* B = C->V->Object(); MhString(C, B, "agent_id", MhAgents[I]);
        MhString(C, B, "model_id", ""); MhSet(C, Bindings, MhRoles[I], B);
    }
    MhSet(C, Team, "roles", Bindings);
    xvalue* Receipt = NULL; Code = MhSave(C, "team", MhUInt(C, Old, "revision"), Team, &Receipt, E);
    C->V->Release(Receipt); C->V->Release(Old);
    if (!Code) { *R = C->V->Clone(Team); MhEmit(C, "mohists.changed", Team); }
    C->V->Release(Team); return Code;
}
static mdo_result MhSnapshot(MhContext* C, const xvalue* Team, xvalue** R, mdo_error_v1* E) {
    *R = C->V->Clone(Team); xvalue* Items = NULL; xvalue* Q = MhParams(C, C->Group);
    MhNumber(C, Q, "limit", 64); mdo_result Code = MhCall(C, "work.list", Q, &Items, E);
    if (!Code) C->V->Set(*R, "tasks", Items); C->V->Release(Items); Items = NULL;
    if (!Code) Code = MhCall(C, "instance.list", MhParams(C, C->Group), &Items, E);
    if (!Code) C->V->Set(*R, "members", Items); C->V->Release(Items);
    return Code;
}
static mdo_result MhConfigure(MhContext* C, const xvalue* P, const xvalue* Envelope,
    xvalue* Team, xvalue** R, mdo_error_v1* E) {
    if (MhCoordinator(C, E)) return MDO_RESULT_ERROR;
    if (MhUInt(C, P, "expected_revision") != MhUInt(C, Envelope, "revision"))
        return MhError(E, "mohists_conflict", "Read the current team revision before editing", 409);
    if (C->V->Count(C->V->Get(Team, "active")) || C->V->Count(C->V->Get(Team, "jobs")))
        return MhError(E, "mohists_team_busy", "Configure role bindings before submitting work", 409);
    const xvalue* Roles = C->V->Get(P, "roles");
    if (Roles) {
        if (C->V->Kind(Roles) != MDO_VALUE_OBJECT) return MhError(E, "mohists_arguments", "roles must be an object", 400);
        for (size_t I = 0; I < C->V->Count(Roles); ++I) {
            const char* K = C->V->Key(Roles, I); const xvalue* B = C->V->Get(Roles, K);
            const char* Agent = MhText(C, B, "agent_id"), *Model = MhText(C, B, "model_id");
            if (MhRole(K) < 0 || !MhId(Agent, 128) || (Model && Model[0] && !MhId(Model, 128)))
                return MhError(E, "mohists_arguments", "Supply known role bindings with portable agent/model ids", 400);
            C->V->Set((xvalue*)C->V->Get(Team, "roles"), K, B);
        }
    }
    const char* Numbers[] = {"concurrency", "max_calls"}; uint64_t Max[] = {3, 128};
    for (int I = 0; I < 2; ++I) if (C->V->Get(P, Numbers[I])) {
        uint64_t N = MhUInt(C, P, Numbers[I]); if (!N || N > Max[I])
            return MhError(E, "mohists_arguments", "concurrency must be 1..3 and max_calls 1..128", 400);
        MhNumber(C, Team, Numbers[I], N);
    }
    xvalue* Receipt = NULL; mdo_result Code = MhSave(C, "team", MhUInt(C, Envelope, "revision"), Team, &Receipt, E);
    C->V->Release(Receipt); if (!Code) { *R = C->V->Clone(Team); MhEmit(C, "mohists.changed", Team); } return Code;
}

#endif
