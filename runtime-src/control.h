#ifndef MOHISTS_CONTROL_H
#define MOHISTS_CONTROL_H

static bool MhTerminal(const MhContext* C, const xvalue* Job) {
    const char* States[] = {"succeeded", "failed", "cancelled", "stale", "timed_out", "limited"};
    for (int I = 0; I < 6; ++I) if (MhIs(C, Job, "state", States[I])) return true;
    return false;
}
static mdo_result MhCancelJobOnce(MhContext* C, const char* Id, const char* Reason,
    xvalue** R, mdo_error_v1* E) {
    xvalue *TE = NULL, *Team = NULL, *JE = NULL, *Job = NULL, *Receipt = NULL;
    mdo_result Code = MhTeamLoad(C, &TE, &Team, E); if (!Code) Code = MhJob(C, Id, &JE, &Job, E);
    if (Code) goto done;
    if (MhTerminal(C, Job)) { *R = C->V->Clone(Job); goto done; }
    bool Active = MhIs(C, Job, "state", "running") || MhIs(C, Job, "state", "starting") || MhIs(C, Job, "state", "cancelling");
    /* Cancellation is not a decision about an uncertain prior side effect.
     * Keep the explicit abandon/recovery path available. */
    if (!MhIs(C, Job, "state", "requires_review"))
        MhString(C, Job, "state", Active ? "cancelling" : !strcmp(Reason, "constraints_changed") ? "stale" : "cancelled");
    MhString(C, Job, "cancel_reason", Reason);
    char Key[80]; MhJobKey(C, Id, Key);
    Code = MhSavePair(C, TE, Team, Key, JE, Job, &Receipt, E); C->V->Release(Receipt); Receipt = NULL;
    if (Code) goto done;
    if (Active) {
        xvalue* Q = MhParams(C, C->Group); MhString(C, Q, "id", MhText(C, Job, "member"));
        Code = MhCall(C, "instance.cancel", Q, &Receipt, E); C->V->Release(Receipt); Receipt = NULL;
        if (Code) goto done;
    }
    xvalue* Q = MhParams(C, C->Group); MhString(C, Q, "id", Id);
    Code = MhCall(C, "work.get", Q, &Receipt, E);
    if (!Code && !MhIs(C, Receipt, "state", "completed") && !MhIs(C, Receipt, "state", "cancelled")) {
        Q = MhParams(C, C->Group); MhString(C, Q, "id", Id);
        MhString(C, Q, "reason", Reason); MhNumber(C, Q, "expected_revision", MhUInt(C, Receipt, "revision"));
        C->V->Release(Receipt); Receipt = NULL; Code = MhCall(C, "work.cancel", Q, &Receipt, E);
    }
    if (!Code) { *R = C->V->Clone(Job); MhEmit(C, "mohists.changed", Job); }
done:
    C->V->Release(Receipt); C->V->Release(TE); C->V->Release(Team); C->V->Release(JE); C->V->Release(Job); return Code;
}
static mdo_result MhCancelJob(MhContext* C, const char* Id, const char* Reason,
    xvalue** R, mdo_error_v1* E) {
    for (int I = 0; I < 8; ++I) {
        mdo_result Code = MhCancelJobOnce(C, Id, Reason, R, E);
        if (!Code || (strcmp(E->Code, "sdk_state_conflict") && strcmp(E->Code, "sdk_work_conflict"))) return Code;
        C->V->Release(*R); *R = NULL;
    }
    return MhError(E, "mohists_busy", "Team changed during cancellation; refresh and retry", 409);
}
static mdo_result MhControl(MhContext* C, const xvalue* P, const char* Action,
    const xvalue* Envelope, xvalue* Team, xvalue** R, mdo_error_v1* E) {
    if (MhCoordinator(C, E)) return MDO_RESULT_ERROR;
    if (!strcmp(Action, "cancel")) return MhCancelJob(C, MhText(C, P, "id"), "user_cancelled", R, E);
    bool Revise = !strcmp(Action, "revise"), Finish = !strcmp(Action, "finish");
    if (MhUInt(C, P, "expected_revision") != MhUInt(C, Envelope, "revision"))
        return MhError(E, "mohists_conflict", "Read the current team revision before changing its goal or lifecycle", 409);
    bool Continuing = (!Revise && !Finish && MhIs(C, Team, "state", "draining")) ||
        (Finish && MhIs(C, Team, "state", "completing")) ||
        (Revise && MhIs(C, Team, "state", "revising") && MhIs(C, Team, "goal", MhText(C, P, "goal") ? MhText(C, P, "goal") : ""));
    if (!MhIs(C, Team, "state", "active") && !Continuing) {
        if (!Revise && !Finish && MhIs(C, Team, "state", "cancelled")) { *R = C->V->Clone(Team); return MDO_RESULT_OK; }
        return MhError(E, "mohists_team_ended", "Wait for this team's current transition to finish", 409);
    }
    if (Finish && C->V->Count(C->V->Get(Team, "active")))
        return MhError(E, "mohists_team_busy", "Finish only after all active member turns have drained", 409);
    const char* Goal = MhText(C, P, "goal");
    if (Revise && (!Goal || !Goal[0] || strlen(Goal) > 4096))
        return MhError(E, "mohists_arguments", "A revised goal of 1..4096 bytes is required", 400);
    if (Revise && !Continuing) {
        MhString(C, Team, "goal", Goal);
        MhNumber(C, Team, "constraint_revision", MhUInt(C, Team, "constraint_revision") + 1);
    }
    MhString(C, Team, "state", Finish ? "completing" : Revise ? "revising" : "draining");
    xvalue* Receipt = NULL; mdo_result Code = Continuing ? MDO_RESULT_OK : MhSave(C, "team", MhUInt(C, Envelope, "revision"), Team, &Receipt, E);
    C->V->Release(Receipt); if (Code) return Code;
    const xvalue* Jobs = C->V->Get(Team, "jobs");
    for (size_t I = 0; I < C->V->Count(Jobs); ++I) {
        /* Completing does not rewrite already finished native results. Queued
         * optional work is cancelled explicitly along with the closing group. */
        xvalue* Result = NULL;
        Code = MhCancelJob(C, C->V->Text(C->V->At(Jobs, I)), Revise ? "constraints_changed" : "user_cancelled", &Result, E);
        C->V->Release(Result); if (Code) return Code;
    }
    xvalue *CurrentEnvelope = NULL, *Current = NULL;
    Code = MhTeamLoad(C, &CurrentEnvelope, &Current, E);
    if (!Code && !C->V->Count(C->V->Get(Current, "active"))) {
        MhString(C, Current, "state", Revise ? "active" : Finish ? "completed" : "cancelled");
        Code = MhSave(C, "team", MhUInt(C, CurrentEnvelope, "revision"), Current, &Receipt, E);
        C->V->Release(Receipt);
    }
    if (!Code) { *R = C->V->Clone(Current); MhEmit(C, "mohists.changed", Current); }
    C->V->Release(Current); C->V->Release(CurrentEnvelope); return Code;
}

#endif
