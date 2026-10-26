#ifndef MOHISTS_RECOVERY_H
#define MOHISTS_RECOVERY_H

static mdo_result MhRecoveryView(MhContext* C, const xvalue* P, const xvalue* Team, xvalue** R, mdo_error_v1* E) {
    if (C->S->RunId && C->S->RunId[0]) return MhError(E, "mohists_recovery_user", "Recovery decisions require a user window", 403);
    mdo_result Code = MhResult(C, P, Team, R, E);
    if (!Code) {
        xvalue* Q = MhParams(C, C->Group), *View = NULL; MhString(C, Q, "id", MhText(C, *R, "member"));
        Code = MhCall(C, "instance.recovery", Q, &View, E);
        if (!Code) C->V->Set(*R, "recovery", View); C->V->Release(View);
    }
    return Code;
}

/* Reconnect refresh harvests durable outcomes, never restarts a member. A
 * missing completion is made explicit instead of guessing which effect ran. */
static mdo_result MhRefresh(MhContext* C, const xvalue* Team, xvalue** R, mdo_error_v1* E) {
    if (MhCoordinator(C, E)) return MDO_RESULT_ERROR;
    const xvalue* Active = C->V->Get(Team, "active");
    mdo_result Code = MDO_RESULT_OK;
    for (size_t I = 0; I < C->V->Count(Active); ++I) {
        const char* Id = C->V->Text(C->V->At(Active, I));
        xvalue *JE = NULL, *Job = NULL, *Member = NULL, *Result = NULL, *Final = NULL;
        Code = MhJob(C, Id, &JE, &Job, E);
        if (!Code) {
            xvalue* Q = MhParams(C, C->Group); MhString(C, Q, "id", MhText(C, Job, "member"));
            Code = MhCall(C, "instance.get", Q, &Member, E);
        }
        if (!Code && !MhIs(C, Member, "state", "running")) {
            const char* Message = MhText(C, Job, "message_id");
            if (Message && Message[0]) {
                xvalue* Q = MhParams(C, C->Group); MhString(C, Q, "id", MhText(C, Job, "member"));
                MhString(C, Q, "message_id", Message); Code = MhCall(C, "instance.result", Q, &Result, E);
                if (Code && E->Status == 404) Code = MDO_RESULT_OK;
            }
            if (!Code) {
                const xvalue* Outcome = C->V->Get(Result, "result");
                Code = MhFinish(C, Id, Outcome, Outcome == NULL, &Final, E);
            }
        }
        C->V->Release(JE); C->V->Release(Job); C->V->Release(Member); C->V->Release(Result); C->V->Release(Final);
        if (Code) return Code;
    }
    xvalue *Envelope = NULL, *Current = NULL; Code = MhTeamLoad(C, &Envelope, &Current, E);
    if (!Code) { Code = MhSnapshot(C, Current, R, E); if (!Code) MhNumber(C, *R, "revision", MhUInt(C, Envelope, "revision")); }
    C->V->Release(Envelope); C->V->Release(Current); return Code;
}
static mdo_result MhAbandon(MhContext* C, const xvalue* P, xvalue** R, mdo_error_v1* E) {
    if (MhCoordinator(C, E)) return MDO_RESULT_ERROR;
    xvalue *JE = NULL, *Job = NULL, *Member = NULL, *Receipt = NULL;
    const char* Id = MhText(C, P, "id"); mdo_result Code = MhJob(C, Id, &JE, &Job, E);
    if (Code) goto done;
    if (!MhIs(C, Job, "state", "requires_review") || MhUInt(C, P, "expected_revision") != MhUInt(C, JE, "revision")) {
        Code = MhError(E, "mohists_conflict", "Inspect the interrupted task's current revision before abandoning it", 409); goto done;
    }
    xvalue* Q = MhParams(C, C->Group); MhString(C, Q, "id", MhText(C, Job, "member"));
    Code = MhCall(C, "instance.get", Q, &Member, E); if (Code) goto done;
    if (MhIs(C, Member, "state", "requires_review")) {
        if (MhUInt(C, P, "expected_member_revision") != MhUInt(C, Member, "revision")) {
            Code = MhError(E, "mohists_conflict", "Inspect the current native member revision before abandoning it", 409); goto done;
        }
        Q = MhParams(C, C->Group); MhString(C, Q, "id", MhText(C, Job, "member"));
        MhString(C, Q, "message_id", MhText(C, Member, "active_message"));
        MhNumber(C, Q, "expected_revision", MhUInt(C, Member, "revision"));
        Code = MhCall(C, "instance.abandon", Q, &Receipt, E);
    } else if (MhIs(C, Member, "state", "idle")) {
        const char* Message = MhText(C, Job, "message_id");
        if (Message && Message[0]) {
            Q = MhParams(C, C->Group); MhString(C, Q, "mailbox", MhText(C, Member, "mailbox"));
            MhString(C, Q, "message_id", Message); Code = MhCall(C, "mailbox.ack", Q, &Receipt, E);
            if (Code && E->Status == 404) Code = MDO_RESULT_OK;
        }
    } else Code = MhError(E, "mohists_member_busy", "Cancel and drain the live member before abandoning its task", 409);
    if (!Code) {
        xvalue* Outcome = C->V->Object(); MhString(C, Outcome, "outcome", "cancelled");
        Code = MhFinish(C, Id, Outcome, false, R, E); C->V->Release(Outcome);
    }
done:
    C->V->Release(JE); C->V->Release(Job); C->V->Release(Member); C->V->Release(Receipt); return Code;
}

#endif
