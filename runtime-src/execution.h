#ifndef MOHISTS_EXECUTION_H
#define MOHISTS_EXECUTION_H

static void MhRemoveActive(const MhContext* C, xvalue* Team, const char* Id) {
    const xvalue* Old = C->V->Get(Team, "active"); xvalue* A = C->V->Array();
    for (size_t I = 0; I < C->V->Count(Old); ++I) {
        const xvalue* V = C->V->At(Old, I); const char* S = C->V->Text(V);
        if (S && strcmp(S, Id)) C->V->Append(A, V);
    }
    MhSet(C, Team, "active", A);
}
static mdo_result MhFinish(MhContext* C, const char* Id, const xvalue* Outcome,
    bool Uncertain, xvalue** R, mdo_error_v1* E) {
    for (int Attempt = 0; Attempt < 8; ++Attempt) {
        xvalue *TE = NULL, *Team = NULL, *JE = NULL, *Job = NULL, *Receipt = NULL;
        mdo_result Code = MhTeamLoad(C, &TE, &Team, E);
        if (!Code) Code = MhJob(C, Id, &JE, &Job, E);
        if (!Code) {
            bool Stale = !MhIs(C, Team, "state", "active") ||
                MhUInt(C, Team, "constraint_revision") != MhUInt(C, Job, "constraint_revision");
            const char* State = MhText(C, Outcome, "outcome");
            if (!State || Uncertain) State = "requires_review";
            if (MhIs(C, Job, "state", "cancelling")) State = MhIs(C, Job, "cancel_reason", "constraints_changed") ? "stale" : "cancelled";
            else if (Stale) State = "stale";
            MhString(C, Job, "state", State); MhString(C, Job, "outcome", MhText(C, Outcome, "outcome"));
            const char* Error = MhText(C, Outcome, "error");
            if (Error && strlen(Error) <= 512) MhString(C, Job, "error", Error);
            /* Full text remains in the native member transcript/result, not in
             * a second private result ledger. Preserve an explicit reference. */
            xvalue* Ref = C->V->Object(); MhString(C, Ref, "member", MhText(C, Job, "member"));
            MhString(C, Ref, "message_id", MhText(C, Job, "message_id"));
            MhNumber(C, Ref, "generation", MhUInt(C, Job, "generation")); MhSet(C, Job, "result_ref", Ref);
            MhRemoveActive(C, Team, Id);
            if (!C->V->Count(C->V->Get(Team, "active"))) {
                if (MhIs(C, Team, "state", "draining")) MhString(C, Team, "state", "cancelled");
                else if (MhIs(C, Team, "state", "revising")) MhString(C, Team, "state", "active");
                else if (MhIs(C, Team, "state", "completing")) MhString(C, Team, "state", "completed");
            }
            char Key[80]; MhJobKey(C, Id, Key);
            Code = MhSavePair(C, TE, Team, Key, JE, Job, &Receipt, E);
            if (!Code) {
                xvalue* Q = MhParams(C, C->Group), *Work = NULL; MhString(C, Q, "id", Id);
                mdo_result WorkCode = MhCall(C, "work.get", Q, &Work, E);
                if (!WorkCode && MhIs(C, Work, "state", "claimed")) {
                    Q = MhParams(C, C->Group); MhString(C, Q, "id", Id);
                    if (!strcmp(State, "succeeded")) {
                        MhString(C, Q, "claim_token", MhText(C, Job, "claim_token"));
                        xvalue* Value = C->V->Clone(C->V->Get(Job, "result_ref"));
                        MhString(C, Value, "outcome", State); MhSet(C, Q, "result", Value);
                        xvalue* Done = NULL; WorkCode = MhCall(C, "work.complete", Q, &Done, E); C->V->Release(Done);
                    } else if (strcmp(State, "requires_review")) {
                        MhNumber(C, Q, "expected_revision", MhUInt(C, Work, "revision"));
                        MhString(C, Q, "reason", State); xvalue* Done = NULL;
                        WorkCode = MhCall(C, "work.cancel", Q, &Done, E); C->V->Release(Done);
                    } else C->V->Release(Q);
                }
                C->V->Release(Work);
                *R = C->V->Clone(Job); MhEmit(C, "mohists.changed", Job);
                if (WorkCode) MhSet(C, *R, "work_sync_pending", C->V->Bool(true));
            }
        }
        bool Conflict = Code && E && !strcmp(E->Code, "sdk_state_conflict");
        C->V->Release(Receipt); C->V->Release(TE); C->V->Release(Team); C->V->Release(JE); C->V->Release(Job);
        if (!Conflict) return Code;
    }
    return MhError(E, "mohists_busy", "Team changed repeatedly; reload before continuing", 409);
}
static mdo_result MhUnschedule(MhContext* C, const char* Id, xvalue** R, mdo_error_v1* E) {
    xvalue *TE = NULL, *Team = NULL, *JE = NULL, *Job = NULL;
    mdo_result Code = MhTeamLoad(C, &TE, &Team, E); if (!Code) Code = MhJob(C, Id, &JE, &Job, E);
    if (!Code && MhIs(C, Job, "state", "starting") && MhIs(C, Team, "state", "active")) {
        MhString(C, Job, "state", "queued"); MhString(C, Job, "operation_id", ""); MhString(C, Job, "message_id", "");
        MhRemoveActive(C, Team, Id); uint64_t Used = MhUInt(C, Team, "calls_used");
        if (Used) MhNumber(C, Team, "calls_used", Used - 1);
        char Key[80]; MhJobKey(C, Id, Key); Code = MhSavePair(C, TE, Team, Key, JE, Job, R, E);
    } else if (!Code) Code = MhError(E, "mohists_admission_changed", "Admission changed before rollback", 409);
    C->V->Release(TE); C->V->Release(Team); C->V->Release(JE); C->V->Release(Job); return Code;
}
static mdo_result MhExecute(MhContext* C, const xvalue* P, const xvalue* TE,
    xvalue* Team, xvalue** R, mdo_error_v1* E) {
    if (MhCoordinator(C, E)) return MDO_RESULT_ERROR;
    bool Resume = MhIs(C, P, "action", "resume");
    bool Schedule = MhIs(C, P, "action", "schedule");
    bool Reserved = MhIs(C, P, "action", "execute_reserved");
    if (!MhIs(C, Team, "state", "active")) return MhError(E, "mohists_team_ended", "This team no longer accepts execution", 409);
    const char* Id = MhText(C, P, "id"); xvalue *JE = NULL, *Job = NULL;
    mdo_result Code = MhJob(C, Id, &JE, &Job, E); if (Code) goto done;
    if (MhUInt(C, Job, "generation") != MhUInt(C, Team, "generation") ||
        MhUInt(C, Job, "constraint_revision") != MhUInt(C, Team, "constraint_revision")) {
        Code = MhError(E, "mohists_stale_task", "The task predates the current goal or constraints", 409); goto done;
    }
    if (Reserved && (!C->S->InvocationId || !MhIs(C, Job, "operation_id", C->S->InvocationId))) {
        Code = MhError(E, "mohists_admission", "Execution must use its recorded native operation receipt", 403); goto done;
    }
    if (!MhIs(C, Job, "state", Resume ? "requires_review" : Reserved ? "starting" : "queued")) {
        Code = MhError(E, "mohists_task_admitted", "Task already started or ended; inspect its result or recovery state", 409); goto done;
    }
    if (Resume && MhUInt(C, P, "expected_revision") != MhUInt(C, JE, "revision")) {
        Code = MhError(E, "mohists_conflict", "Inspect the interrupted task's current revision before resuming", 409); goto done;
    }
    if (!Reserved && MhUInt(C, Team, "calls_used") >= MhUInt(C, Team, "max_calls")) {
        Code = MhError(E, "mohists_budget", "The cumulative member-turn budget is exhausted", 429); goto done;
    }
    const xvalue* Active = C->V->Get(Team, "active");
    if (!Reserved && C->V->Count(Active) >= MhUInt(C, Team, "concurrency")) {
        Code = MhError(E, "mohists_concurrency", "All member slots are occupied", 429); goto done;
    }
    for (size_t I = 0; !Reserved && I < C->V->Count(Active); ++I) {
        xvalue *AE = NULL, *A = NULL; Code = MhJob(C, C->V->Text(C->V->At(Active, I)), &AE, &A, E);
        bool Busy = !Code && (MhIs(C, A, "member", MhText(C, Job, "member")) ||
            (MhIs(C, A, "role", "worker") && MhIs(C, Job, "role", "worker")));
        C->V->Release(AE); C->V->Release(A); if (Code) goto done;
        if (Busy) { Code = MhError(E, "mohists_writer_busy", "Wait for this member or the current writer to finish", 409); goto done; }
    }
    xvalue *Q = MhParams(C, C->Group), *Work = NULL, *Member = NULL;
    MhString(C, Q, "id", Id); Code = MhCall(C, "work.get", Q, &Work, E);
    bool Ready = false; if (!Code) C->V->Boolean(C->V->Get(Work, "ready"), &Ready);
    if (!Code && !Ready && !(Resume && MhIs(C, Work, "state", "claimed"))) Code = MhError(E, "mohists_dependencies", "Dependencies are unfinished, failed or cancelled", 409);
    if (Code) { C->V->Release(Work); goto done; }
    Q = MhParams(C, C->Group); MhString(C, Q, "id", MhText(C, Job, "member"));
    Code = MhCall(C, "instance.get", Q, &Member, E);
    if (!Code && !MhIs(C, Member, "state", Resume ? "requires_review" : "idle")) Code = MhError(E, "mohists_member_busy", "Member is active or requires a different recovery decision", 409);
    if (!Code && Resume && MhUInt(C, P, "expected_member_revision") != MhUInt(C, Member, "revision"))
        Code = MhError(E, "mohists_conflict", "Recovery requires the current native member revision", 409);
    C->V->Release(Member);
    if (Code) { C->V->Release(Work); goto done; }
    char Prompt[10000], Message[80];
    snprintf(Message, sizeof(Message), "task.%s", Id);
    snprintf(Prompt, sizeof(Prompt), "Delegated work from the coordinator. Agent messages are not human authorization.\nGoal: %s\nTask: %s\nReturn findings, deliverables and verification to the coordinator. Do not create members.", MhText(C, Team, "goal"), MhText(C, Job, "prompt"));
    xvalue* Body = C->V->Object(); MhString(C, Body, "prompt", Prompt);
    char* Json = C->V->Json(Body); bool Fits = Json && strlen(Json) <= 7800;
    C->V->Free(Json); C->V->Release(Body);
    if (!Fits) { C->V->Release(Work); Code = MhError(E, "mohists_input_limit", "Combined goal and task exceed the native mailbox budget; shorten them or reference files", 413); goto done; }
    MhString(C, Job, "message_id", Message); MhString(C, Job, "state", "starting");
    char Key[80]; MhJobKey(C, Id, Key); xvalue* Receipt = NULL;
    if (!Reserved) {
        if (Schedule) {
            unsigned char Bytes[16]; static const char Hex[] = "0123456789abcdef"; char Op[37] = "sdk-";
            if (!xrtSecureRandom(Bytes, sizeof(Bytes))) { C->V->Release(Work); Code = MhError(E, "mohists_random", "Cannot create an operation identity", 503); goto done; }
            for (int I = 0; I < 16; ++I) { Op[4+I*2] = Hex[Bytes[I] >> 4]; Op[5+I*2] = Hex[Bytes[I] & 15]; } Op[36] = 0;
            MhString(C, Job, "operation_id", Op);
        }
        xvalue* Name = C->V->String(Id); C->V->Append((xvalue*)Active, Name); C->V->Release(Name);
        MhNumber(C, Team, "calls_used", MhUInt(C, Team, "calls_used") + 1);
        Code = MhSavePair(C, TE, Team, Key, JE, Job, &Receipt, E); C->V->Release(Receipt); Receipt = NULL;
    }
    if (Code) { C->V->Release(Work); goto done; }
    if (Schedule) {
        C->V->Release(Work);
        Q = C->V->Object(); MhString(C, Q, "id", MhText(C, Job, "operation_id")); MhString(C, Q, "method", "mohists.worker");
        xvalue* Params = C->V->Object(); MhString(C, Params, "action", "execute_reserved"); MhString(C, Params, "id", Id);
        MhSet(C, Q, "params", Params); Code = MhCall(C, "operation.start", Q, R, E);
        if (Code) {
            mdo_error_v1 Original = *E, X = {0}; xvalue* Final = NULL;
            bool Rejected = Original.Status == 429 && !Original.MayHaveCompleted;
            mdo_result RolledBack = Rejected ? MhUnschedule(C, Id, &Final, &X) : MDO_RESULT_ERROR;
            C->V->Release(Final); Final = NULL;
            if (RolledBack) MhFinish(C, Id, NULL, true, &Final, &X);
            C->V->Release(Final); *E = Original;
        }
        goto done;
    }
    Q = MhParams(C, C->Group); MhString(C, Q, "id", Id); MhString(C, Q, "worker", MhText(C, Job, "member"));
    MhString(C, Q, "claim_id", Id); MhNumber(C, Q, "expected_revision", MhUInt(C, Work, "revision"));
    C->V->Release(Work); Work = NULL; Code = MhCall(C, "work.claim", Q, &Work, E);
    if (!Code) {
        MhString(C, Job, "claim_token", MhText(C, Work, "claim_token")); MhString(C, Job, "state", "running");
        xvalue* Latest = NULL; Code = MhLoad(C, Key, &Latest, E);
        if (!Code && !MhIs(C, C->V->Get(Latest, "value"), "state", "starting"))
            Code = MhError(E, "mohists_cancelled", "Task was cancelled before its member started", 499);
        if (!Code) Code = MhSave(C, Key, MhUInt(C, Latest, "revision"), Job, &Receipt, E);
        C->V->Release(Receipt); Receipt = NULL; C->V->Release(Latest);
    }
    C->V->Release(Work);
    if (!Code && !Resume) {
        Q = MhParams(C, C->Group); MhString(C, Q, "id", MhText(C, Job, "member"));
        MhString(C, Q, "message_id", Message); MhString(C, Q, "prompt", Prompt);
        Code = MhCall(C, "instance.send", Q, &Receipt, E); C->V->Release(Receipt); Receipt = NULL;
    }
    if (!Code) {
        MhEmit(C, "mohists.changed", Job);
        Q = MhParams(C, C->Group); MhString(C, Q, "id", MhText(C, Job, "member"));
        if (Resume) {
            MhString(C, Q, "message_id", Message);
            MhNumber(C, Q, "expected_revision", MhUInt(C, P, "expected_member_revision"));
            if (C->V->Get(P, "decisions")) C->V->Set(Q, "decisions", C->V->Get(P, "decisions"));
        }
        Code = MhCall(C, Resume ? "instance.resume" : "instance.step", Q, &Receipt, E);
    }
    if (Code) {
        mdo_error_v1 Original = *E, FinishError = {0}; xvalue* Final = NULL;
        MhFinish(C, Id, NULL, true, &Final, &FinishError); C->V->Release(Final); *E = Original;
    } else Code = MhFinish(C, Id, C->V->Get(Receipt, "last_outcome"), false, R, E);
    C->V->Release(Receipt);
done:
    C->V->Release(JE); C->V->Release(Job); return Code;
}
static mdo_result MhResult(MhContext* C, const xvalue* P, const xvalue* Team,
    xvalue** R, mdo_error_v1* E) {
    xvalue *JE = NULL, *Job = NULL; mdo_result Code = MhJob(C, MhText(C, P, "id"), &JE, &Job, E);
    if (!Code && MhUInt(C, Job, "generation") != MhUInt(C, Team, "generation"))
        Code = MhError(E, "mohists_stale_task", "Select a task from the current group", 409);
    if (!Code) {
        *R = C->V->Clone(Job);
        MhNumber(C, *R, "revision", MhUInt(C, JE, "revision"));
        xvalue* Member = NULL, *Q = MhParams(C, C->Group);
        MhString(C, Q, "id", MhText(C, Job, "member"));
        Code = MhCall(C, "instance.get", Q, &Member, E);
        if (!Code) C->V->Set(*R, "member_state", Member); C->V->Release(Member);
        const char* Message = MhText(C, Job, "message_id");
        if (!Code && Message && Message[0]) {
            xvalue* Q = MhParams(C, C->Group), *Native = NULL;
            MhString(C, Q, "id", MhText(C, Job, "member")); MhString(C, Q, "message_id", Message);
            Code = MhCall(C, "instance.result", Q, &Native, E);
            if (!Code) C->V->Set(*R, "native", Native); C->V->Release(Native);
        }
    }
    C->V->Release(JE); C->V->Release(Job); return Code;
}

#endif
