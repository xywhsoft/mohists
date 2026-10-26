#ifndef MOHISTS_SCHEDULER_H
#define MOHISTS_SCHEDULER_H

static void MhReap(const MhContext* C) {
    xvalue* Ops = NULL; mdo_error_v1 E = {0};
    if (mdoCall(C->S, "operation.list", NULL, &Ops, &E)) return;
    for (size_t I = 0; I < C->V->Count(Ops); ++I) {
        const xvalue* Op = C->V->At(Ops, I); bool Terminal = false;
        C->V->Boolean(C->V->Get(Op, "terminal"), &Terminal);
        if (!Terminal || !MhIs(C, Op, "method", "mohists.worker")) continue;
        const char* Id = MhText(C, Op, "id");
        if (Id && (!C->S->InvocationId || strcmp(Id, C->S->InvocationId))) {
            xvalue* Q = C->V->Object(), *Released = NULL; MhString(C, Q, "id", Id);
            MhCall(C, "operation.release", Q, &Released, &E); C->V->Release(Released);
        }
    }
    C->V->Release(Ops);
}

static mdo_result MhPump(MhContext* C, xvalue** R, mdo_error_v1* E) {
    /* Native member results are already durable before worker completion.
     * Reap only this dedicated worker service, preserving unrelated results. */
    MhReap(C);
    xvalue *TE = NULL, *Team = NULL; mdo_result Code = MhTeamLoad(C, &TE, &Team, E);
    if (Code) goto done;
    if (!MhIs(C, Team, "state", "active")) { Code = MhSnapshot(C, Team, R, E); goto done; }
    const xvalue* Jobs = C->V->Get(Team, "jobs");
    for (size_t I = 0; I < C->V->Count(Jobs); ++I) {
        const char* Id = C->V->Text(C->V->At(Jobs, I)); xvalue *JE = NULL, *Job = NULL, *Receipt = NULL;
        Code = MhJob(C, Id, &JE, &Job, E); bool Requested = false;
        if (!Code) C->V->Boolean(C->V->Get(Job, "requested"), &Requested);
        if (!Code && Requested && MhIs(C, Job, "state", "queued")) {
            xvalue *CurrentEnvelope = NULL, *Current = NULL;
            Code = MhTeamLoad(C, &CurrentEnvelope, &Current, E);
            if (!Code && MhIs(C, Current, "state", "active")) {
                xvalue* Q = C->V->Object(); MhString(C, Q, "action", "schedule"); MhString(C, Q, "id", Id);
                Code = MhExecute(C, Q, CurrentEnvelope, Current, &Receipt, E); C->V->Release(Q);
                /* A dependency or occupied slot is durable waiting, not a
                 * failed task. The next real completion pumps this queue. */
                if (Code && (!strcmp(E->Code, "mohists_dependencies") || !strcmp(E->Code, "mohists_writer_busy") ||
                    !strcmp(E->Code, "mohists_concurrency") || !strcmp(E->Code, "mohists_task_admitted") ||
                    !strcmp(E->Code, "sdk_state_conflict") || !strcmp(E->Code, "mohists_budget") ||
                    !strcmp(E->Code, "sdk_operation_limit"))) Code = MDO_RESULT_OK;
            }
            C->V->Release(CurrentEnvelope); C->V->Release(Current);
        }
        C->V->Release(JE); C->V->Release(Job); C->V->Release(Receipt); if (Code) goto done;
    }
    C->V->Release(TE); C->V->Release(Team); TE = NULL; Team = NULL;
    Code = MhTeamLoad(C, &TE, &Team, E);
    if (!Code) { Code = MhSnapshot(C, Team, R, E); if (!Code) MhNumber(C, *R, "revision", MhUInt(C, TE, "revision")); }
done:
    C->V->Release(TE); C->V->Release(Team); return Code;
}
static mdo_result MhRun(MhContext* C, const xvalue* P, const xvalue* Team, xvalue** R, mdo_error_v1* E) {
    if (MhCoordinator(C, E)) return MDO_RESULT_ERROR;
    if (!MhIs(C, Team, "state", "active")) return MhError(E, "mohists_team_ended", "The group is not accepting work", 409);
    const char* Selected = MhText(C, P, "id"); const xvalue* Jobs = C->V->Get(Team, "jobs");
    if (Selected && !MhId(Selected, 48)) return MhError(E, "mohists_arguments", "Supply a valid task id, or omit id to run the queue", 400);
    bool Found = !Selected;
    for (size_t I = 0; I < C->V->Count(Jobs); ++I) {
        const char* Id = C->V->Text(C->V->At(Jobs, I)); if (Selected && strcmp(Selected, Id)) continue; Found = true;
        xvalue *JE = NULL, *Job = NULL, *Receipt = NULL; mdo_result Code = MhJob(C, Id, &JE, &Job, E);
        if (!Code && MhIs(C, Job, "state", "queued")) {
            bool Requested = false; C->V->Boolean(C->V->Get(Job, "requested"), &Requested);
            if (!Requested) {
                MhSet(C, Job, "requested", C->V->Bool(true)); char Key[80]; MhJobKey(C, Id, Key);
                Code = MhSave(C, Key, MhUInt(C, JE, "revision"), Job, &Receipt, E);
            }
        }
        C->V->Release(JE); C->V->Release(Job); C->V->Release(Receipt); if (Code) return Code;
    }
    if (!Found) return MhError(E, "mohists_task_missing", "Task is not in the current group", 404);
    return MhPump(C, R, E);
}
static mdo_result MhWait(MhContext* C, const xvalue* P, xvalue** R, mdo_error_v1* E) {
    uint64_t Timeout = C->V->Get(P, "timeout_ms") ? MhUInt(C, P, "timeout_ms") : 10000;
    if (Timeout > 60000) return MhError(E, "mohists_arguments", "timeout_ms must be 0..60000", 400);
    uint64_t End = C->S->Api->MonotonicMicroseconds() + Timeout * 1000;
    for (;;) {
        xvalue* Events = NULL; mdo_result Code = mdoCall(C->S, "events.read", NULL, &Events, E); if (Code) return Code;
        xvalue* Q = C->V->Object(); C->V->Set(Q, "after", C->V->Get(Events, "latest"));
        C->V->Set(Q, "epoch", C->V->Get(Events, "epoch")); C->V->Release(Events); Events = NULL;
        xvalue* Pumped = NULL; Code = MhPump(C, &Pumped, E); C->V->Release(Pumped);
        if (Code) { C->V->Release(Q); return Code; }
        xvalue *TE = NULL, *Team = NULL; Code = MhTeamLoad(C, &TE, &Team, E);
        bool Busy = !Code && C->V->Count(C->V->Get(Team, "active")) > 0;
        if (!Code && !Busy && MhIs(C, Team, "state", "active") && MhUInt(C, Team, "calls_used") < MhUInt(C, Team, "max_calls")) {
            const xvalue* Jobs = C->V->Get(Team, "jobs");
            for (size_t I = 0; !Busy && I < C->V->Count(Jobs); ++I) {
                xvalue *JE = NULL, *Job = NULL, *Work = NULL; bool Requested = false;
                Code = MhJob(C, C->V->Text(C->V->At(Jobs, I)), &JE, &Job, E);
                if (!Code) C->V->Boolean(C->V->Get(Job, "requested"), &Requested);
                if (!Code && Requested && MhIs(C, Job, "state", "queued")) {
                    xvalue* Query = MhParams(C, C->Group); MhString(C, Query, "id", MhText(C, Job, "id"));
                    Code = MhCall(C, "work.get", Query, &Work, E);
                    if (!Code) C->V->Boolean(C->V->Get(Work, "ready"), &Busy);
                }
                C->V->Release(JE); C->V->Release(Job); C->V->Release(Work); if (Code) break;
            }
        }
        if (!Code) { Code = MhSnapshot(C, Team, R, E); if (!Code) MhNumber(C, *R, "revision", MhUInt(C, TE, "revision")); }
        C->V->Release(TE); C->V->Release(Team);
        uint64_t Now = C->S->Api->MonotonicMicroseconds();
        if (Code || !Busy || Now >= End || C->S->Api->Cancelled(C->S)) { C->V->Release(Q); return Code; }
        C->V->Release(*R); *R = NULL;
        uint64_t Ms = (End - Now + 999) / 1000; MhNumber(C, Q, "timeout_ms", Ms > 1000 ? 1000 : Ms);
        MhString(C, Q, "topic", "mohists.changed"); Code = MhCall(C, "events.wait", Q, &Events, E);
        C->V->Release(Events); if (Code) return Code;
    }
}

#endif
