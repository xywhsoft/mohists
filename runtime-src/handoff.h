#ifndef MOHISTS_HANDOFF_H
#define MOHISTS_HANDOFF_H

static mdo_result MhExecutionTarget(void* User,const mdo_sdk_context_v1* S,const char* Topic,
    const xvalue* Input,xvalue** Replacement,mdo_error_v1* E){
    (void)User;(void)Topic;if(!S->SessionId||!S->SessionId[0])return MDO_RESULT_OK;
    MhContext C;mdo_result Code=MhContextInit(&C,S,E);if(Code)return Code;
    xvalue *TE=NULL,*Team=NULL;Code=MhTeamLoad(&C,&TE,&Team,E);
    if(Code&&!strcmp(E->Code,"mohists_team_missing"))Code=MDO_RESULT_OK;
    else if(!Code&&!MhIs(&C,Team,"speaker","coordinator")){
        if(C.V->Get(Input,"target"))Code=MhError(E,"mohists_route_conflict","Another extension already selected the main speaker",409);
        else{
            *Replacement=C.V->Clone(Input);xvalue* Target=MhParams(&C,C.Group);
            MhString(&C,Target,"id",MhText(&C,Team,"speaker"));MhSet(&C,*Replacement,"target",Target);
        }
    }
    C.V->Release(TE);C.V->Release(Team);return Code;
}

/* The selected speaker is session state, never the configured/global Agent.
 * A main turn enters the same work/slot/budget admission as delegated work. */
static bool MhTalkId(const char* Run, char Id[49]) {
    unsigned char Digest[32]; xsha256 Sha;
    if (!Run || !Run[0]) return false;
    xrtSha256Init(&Sha);
    if (!xrtSha256Update(&Sha, Run, strlen(Run)) || !xrtSha256Final(&Sha, Digest)) return false;
    memcpy(Id, "talk.", 5);
    for (int I = 0; I < 20; ++I) snprintf(Id + 5 + I * 2, 3, "%02x", Digest[I]);
    return true;
}
static mdo_result MhHandoff(MhContext* C, const xvalue* P, const xvalue* Envelope,
    xvalue* Team, xvalue** R, mdo_error_v1* E) {
    if (MhCoordinator(C, E)) return MDO_RESULT_ERROR;
    if (mdoCallOrigin(C->S) != MDO_ORIGIN_USER)
        return MhError(E, "mohists_handoff_user", "Only the user can explicitly change the main speaker", 403);
    if (MhUInt(C, P, "expected_revision") != MhUInt(C, Envelope, "revision"))
        return MhError(E, "mohists_conflict", "Refresh before changing the main speaker", 409);
    const char* Target = MhText(C, P, "member");
    if (!MhId(Target, 48)) return MhError(E, "mohists_arguments", "Choose a member, or coordinator", 400);
    xvalue *Q = C->V->Object(), *Path = C->V->Object(), *Owner = NULL;
    MhString(C, Path, "project", C->S->ProjectId); MhString(C, Path, "session", C->S->SessionId); MhSet(C, Q, "path", Path);
    mdo_result Code = MhCall(C, "session.get", Q, &Owner, E); bool Busy = false;
    if (!Code) C->V->Boolean(C->V->Get(C->V->Get(Owner, "data"), "runtime_open"), &Busy);
    C->V->Release(Owner); if (Code) return Code;
    if (Busy) return MhError(E, "mohists_main_busy", "Wait for or stop the main conversation before handing it over", 409);
    xvalue* Binding = NULL;
    if (strcmp(Target, "coordinator")) {
        if (!MhIs(C, Team, "state", "active") || C->V->Count(C->V->Get(Team, "active")))
            return MhError(E, "mohists_team_busy", "Drain active tasks before choosing a main speaker", 409);
        const xvalue* Jobs = C->V->Get(Team, "jobs");
        for (size_t I = 0; I < C->V->Count(Jobs); ++I) {
            xvalue *JE = NULL, *Job = NULL; Code = MhJob(C, C->V->Text(C->V->At(Jobs, I)), &JE, &Job, E);
            if (!Code && MhIs(C, Job, "member", Target)) { C->V->Release(Binding); Binding = C->V->Clone(Job); }
            C->V->Release(JE); C->V->Release(Job); if (Code) break;
        }
        if (!Code && !Binding) Code = MhError(E, "mohists_member_missing", "Select an existing member in this group", 404);
        xvalue* Native = NULL;
        if (!Code) { Q = MhParams(C, C->Group); MhString(C, Q, "id", Target); Code = MhCall(C, "instance.get", Q, &Native, E); }
        if (!Code && !MhIs(C, Native, "state", "idle")) Code = MhError(E, "mohists_member_busy", "Resolve or drain this member before handing over", 409);
        C->V->Release(Native);
        if (!Code && MhIs(C, Binding, "role", "worker")) Code = MhPendingReview(C, Team, NULL, true, E);
    }
    if (!Code && !MhIs(C, Team, "speaker", Target)) {
        if (!MhIs(C, Team, "speaker", "coordinator")) {
            MhString(C, Team, "last_speaker", MhText(C, Team, "speaker"));
            if (C->V->Get(Team, "speaker_binding")) C->V->Set(Team, "last_speaker_binding", C->V->Get(Team, "speaker_binding"));
        }
        MhString(C, Team, "speaker", Target);
        xvalue* Selected = C->V->Object();
        if (Binding) {
            const char* Fields[] = {"member", "role", "agent_id", "model_id"};
            for (int I = 0; I < 4; ++I) MhString(C, Selected, Fields[I], MhText(C, Binding, Fields[I]));
        }
        MhSet(C, Team, "speaker_binding", Selected);
        MhNumber(C, Team, "handoff_revision", MhUInt(C, Team, "handoff_revision") + 1);
        xvalue* Saved = NULL; Code = MhSave(C, "team", MhUInt(C, Envelope, "revision"), Team, &Saved, E); C->V->Release(Saved);
        if (!Code) MhEmit(C, "mohists.changed", Team);
    }
    C->V->Release(Binding); if (!Code) *R = C->V->Clone(Team); return Code;
}
static mdo_result MhRoute(void* User, const mdo_sdk_context_v1* S, const char* Topic,
    const xvalue* Input, xvalue** Replacement, mdo_error_v1* E) {
    (void)User; (void)Topic;
    if (!S->SessionId || !S->SessionId[0] || (S->MemberId && S->MemberId[0])) return MDO_RESULT_OK;
    MhContext C; mdo_result Code = MhContextInit(&C, S, E); if (Code) return Code;
    xvalue *TE = NULL, *Team = NULL, *Assigned = NULL, *Route = NULL;
    Code = MhTeamLoad(&C, &TE, &Team, E);
    if (Code && !strcmp(E->Code, "mohists_team_missing")) { Code = MDO_RESULT_OK; goto done; }
    if (Code || MhIs(&C, Team, "speaker", "coordinator")) goto done;
    bool Resume = false; C.V->Boolean(C.V->Get(Input, "resume"), &Resume);
    if (Resume) { Code = MhError(E, "mohists_main_recovery", "Use this member's explicit recovery window before resuming", 409); goto done; }
    if (C.V->Get(Input, "route")) { Code = MhError(E, "mohists_route_conflict", "Another extension already selected a main-chat route", 409); goto done; }
    const char* Run = MhText(&C, Input, "run_id"); char Id[49];
    if (!MhTalkId(Run, Id)) { Code = MhError(E, "mohists_run_id", "Cannot identify the main-chat turn", 500); goto done; }
    uint64_t Epoch = MhUInt(&C, Team, "handoff_revision");
    const xvalue* Binding = C.V->Get(Team, "speaker_binding");
    xvalue* Q = C.V->Object(); MhString(&C, Q, "id", Id);
    MhString(&C, Q, "member", MhText(&C, Team, "speaker")); MhString(&C, Q, "role", MhText(&C, Binding, "role"));
    MhString(&C, Q, "title", "主对话 · 用户输入");
    MhString(&C, Q, "prompt", "The actual main input and its attachments are stored in this member's native conversation, not in this task summary.");
    Code = MhAssignImpl(&C, Q, TE, Team, Run, &Assigned, E); C.V->Release(Q); if (Code) goto done;
    C.V->Release(TE); TE = NULL; C.V->Release(Team); Team = NULL;
    Code = MhTeamLoad(&C, &TE, &Team, E);
    if (!Code && Epoch != MhUInt(&C, Team, "handoff_revision")) Code = MhError(E, "mohists_conflict", "Main speaker changed while preparing this turn", 409);
    if (!Code) {
        Q = C.V->Object(); MhString(&C, Q, "action", "route_prepare"); MhString(&C, Q, "id", Id);
        Code = MhExecute(&C, Q, TE, Team, &Route, E); C.V->Release(Q);
    }
    if (!Code) {
        xvalue* Meta = C.V->Object(); MhString(&C, Meta, "plugin", "mohists"); MhString(&C, Meta, "job_id", Id);
        MhNumber(&C, Meta, "generation", C.Generation); MhNumber(&C, Meta, "handoff_revision", Epoch); MhSet(&C, Route, "context", Meta);
        *Replacement = C.V->Clone(Input); C.V->Set(*Replacement, "route", Route);
    }
done:
    C.V->Release(TE); C.V->Release(Team); C.V->Release(Assigned); C.V->Release(Route); return Code;
}
static mdo_result MhRouteFinished(void* User, const mdo_sdk_context_v1* S, const char* Topic,
    const xvalue* Input, xvalue** Replacement, mdo_error_v1* E) {
    (void)User; (void)Topic; (void)Replacement;
    if (!S->SessionId || !S->SessionId[0]) return MDO_RESULT_OK;
    const mdo_values_v1* V = S->Api->Values; bool External = false;
    V->Boolean(V->Get(Input, "external_settlement"), &External); if (External) return MDO_RESULT_OK;
    const xvalue* Route = V->Get(Input, "route"), *Meta = V->Get(Route, "context");
    const char* Plugin = V->Text(V->Get(Meta, "plugin"));
    if (Route && (!Plugin || strcmp(Plugin, "mohists"))) return MDO_RESULT_OK;
    MhContext C; mdo_result Code = MhContextInit(&C, S, E); if (Code) return Code;
    xvalue *TE = NULL, *Team = NULL, *JE = NULL, *Job = NULL, *Final = NULL;
    Code = MhTeamLoad(&C, &TE, &Team, E);
    if (Code && !strcmp(E->Code, "mohists_team_missing")) { Code = MDO_RESULT_OK; goto done; }
    if (Code) goto done;
    if (Meta && MhUInt(&C, Meta, "generation") != C.Generation) { Code = MDO_RESULT_OK; goto done; }
    char Id[49]; const char* Run = MhText(&C, Input, "run_id");
    if (!MhTalkId(Run, Id)) { Code = MDO_RESULT_OK; goto done; }
    Code = MhJob(&C, Id, &JE, &Job, E);
    if (Code && !strcmp(E->Code, "mohists_task_missing")) { Code = MDO_RESULT_OK; goto done; }
    if (Code || !MhIs(&C, Job, "main_run_id", Run) || MhTerminal(&C, Job)) goto done;
    const xvalue* Outcome = C.V->Get(C.V->Get(Input, "member"), "last_outcome");
    xvalue* Failed = NULL;
    if (!Outcome) {
        bool Started = false; C.V->Boolean(C.V->Get(Input, "started"), &Started);
        if (!Started) { Failed = C.V->Object(); MhString(&C, Failed, "outcome", "failed"); MhString(&C, Failed, "error", MhText(&C, Input, "error")); Outcome = Failed; }
    }
    Code = MhFinish(&C, Id, Outcome, Outcome == NULL, &Final, E); C.V->Release(Failed);
done:
    C.V->Release(TE); C.V->Release(Team); C.V->Release(JE); C.V->Release(Job); C.V->Release(Final); return Code;
}
static mdo_result MhReleased(void* User, const mdo_sdk_context_v1* S, const char* Topic,
    const xvalue* Input, xvalue** Replacement, mdo_error_v1* E) {
    (void)User; (void)Topic; (void)Replacement;
    if (!S->SessionId || !S->SessionId[0] || (S->MemberId && S->MemberId[0])) return MDO_RESULT_OK;
    MhContext C; mdo_result Code = MhContextInit(&C, S, E); if (Code) return Code;
    xvalue *TE = NULL, *Team = NULL, *Next = NULL;
    Code = MhTeamLoad(&C, &TE, &Team, E);
    if (Code && !strcmp(E->Code, "mohists_team_missing")) Code = MDO_RESULT_OK;
    else if (!Code && MhIs(&C, Input, "namespace", C.Group)) Code = MhPump(&C, &Next, E);
    C.V->Release(TE); C.V->Release(Team); C.V->Release(Next); return Code;
}

#endif
