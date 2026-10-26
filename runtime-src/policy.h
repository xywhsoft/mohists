#ifndef MOHISTS_POLICY_H
#define MOHISTS_POLICY_H

/* Scope the hook to this plugin's owning session/member namespace. It guards
 * actual effect boundaries, including the cancellation-before-step window. */
static mdo_result MhPolicy(void* User, mdo_agent_phase Phase,
    const mdo_agent_context_v1* A, char* Error, size_t Capacity) {
    (void)User;
    bool Member = A->Namespace && !strncmp(A->Namespace, "mohists.", 8) && A->MemberId && A->MemberId[0];
    bool Coordinator = A->AgentId && !strcmp(A->AgentId, "agent.mohists");
    if ((!Member && !Coordinator) || !A->Application) return MDO_RESULT_OK;
    if (Phase == MDO_AGENT_BEFORE_DELEGATE) {
        snprintf(Error, Capacity, "Use the Mohists team tool; recursive or unbudgeted delegation is disabled");
        return MDO_RESULT_ERROR;
    }
    MhContext C; mdo_error_v1 E = {0};
    mdo_result Code = MhContextInit(&C, A->Application, &E);
    xvalue *Envelope = NULL, *Team = NULL;
    if (!Code) Code = MhTeamLoad(&C, &Envelope, &Team, &E);
    if (Code && !Member && !strcmp(E.Code, "mohists_team_missing")) Code = MDO_RESULT_OK;
    else if (!Code && Member) {
        bool Allowed = false; const xvalue* Active = C.V->Get(Team, "active");
        for (size_t I = 0; I < C.V->Count(Active); ++I) {
            xvalue *JE = NULL, *Job = NULL;
            mdo_result Check = MhJob(&C, C.V->Text(C.V->At(Active, I)), &JE, &Job, &E);
            if (!Check && MhIs(&C, Job, "member", A->MemberId) && MhIs(&C, Job, "state", "running") &&
                MhIs(&C, Team, "state", "active") && MhUInt(&C, Job, "constraint_revision") == MhUInt(&C, Team, "constraint_revision")) {
                Allowed = true;
                xwork_agent_extension_context* Native = mdoAgentNative(A);
                const xwork_hook_event* Event = Native ? Native->pToolEvent : NULL;
                if (Phase == MDO_AGENT_BEFORE_TOOL && Event && !MhIs(&C, Job, "role", "worker") &&
                    (Event->uEffects & ~((uint64_t)MDO_TOOL_EFFECT_READ)))
                    Code = MhError(&E, "mohists_read_only", "Research and review members may only use read-only tools, including with custom role bindings", 403);
            }
            C.V->Release(JE); C.V->Release(Job); if (Check) { Code = Check; break; }
        }
        if (!Code && !Allowed) Code = MhError(&E, "mohists_cancelled", "This member's task was cancelled, superseded or never admitted", 499);
    } else if (!Code && Coordinator && Phase == MDO_AGENT_BEFORE_TOOL) {
        xwork_agent_extension_context* Native = mdoAgentNative(A);
        const xwork_hook_event* Event = Native ? Native->pToolEvent : NULL;
        if (Event && (Event->uEffects & (MDO_TOOL_EFFECT_WORKSPACE_WRITE | MDO_TOOL_EFFECT_PROCESS))) {
            const xvalue* Active = C.V->Get(Team, "active");
            for (size_t I = 0; I < C.V->Count(Active); ++I) {
                xvalue *JE = NULL, *Job = NULL;
                Code = MhJob(&C, C.V->Text(C.V->At(Active, I)), &JE, &Job, &E);
                bool Writer = !Code && MhIs(&C, Job, "role", "worker"); C.V->Release(JE); C.V->Release(Job);
                if (Writer) Code = MhError(&E, "mohists_writer_busy", "Wait for the active writer before changing the same workspace", 409);
                if (Code) break;
            }
        }
    }
    if (!Code && Coordinator && Phase == MDO_AGENT_CONTEXT) {
        xvalue *DE=NULL,*Defaults=NULL;
        const xvalue* Config=Team;
        if (!Config) { Code=MhSettingsLoad(&C,&DE,&Defaults,&E); Config=Defaults; }
        xvalue* Source=mdoAgentContextSource(A,"system");
        const char* Before=MhText(&C,Source,"text");
        const char* Mode=MhIs(&C,Config,"mode","requested") ?
            "Only start collaboration after the user explicitly starts a team in the collaboration window. Otherwise work directly; do not bypass with ordinary delegation." :
            "Use collaboration only when division of work has actual value. Handle simple work directly.";
        const char* Review=MhIs(&C,Config,"review","always") ?
            "Every completed worker task needs a successful independent reviewer task with depends_on naming that worker task before finish. Reserve review turns in the cumulative budget." :
            MhIs(&C,Config,"review","off") ? "Do not automatically create review tasks. The user can still explicitly ask for review." :
            "Choose independent review when changes or uncertainty warrant it; do not force a review pipeline for simple tasks.";
        char* Text=!Code && Before ? xrtFormat("%s\nMohists user preferences:\n%s\n%s",Before,Mode,Review) : NULL;
        if (!Code && (!Text || !mdoAgentSetContextText(A,"system",Text))) Code=MhError(&E,"mohists_context","Cannot apply collaboration preferences",500);
        xrtFree(Text); C.V->Release(DE); C.V->Release(Defaults);
    }
    C.V->Release(Envelope); C.V->Release(Team);
    if (Code) snprintf(Error, Capacity, "%s", E.Message);
    return Code;
}

#endif
