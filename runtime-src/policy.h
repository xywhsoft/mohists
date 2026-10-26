#ifndef MOHISTS_POLICY_H
#define MOHISTS_POLICY_H

/* Scope the hook to this plugin's owning session/member namespace. It guards
 * actual effect boundaries, including the cancellation-before-step window. */
static mdo_result MhPolicy(void* User, mdo_agent_phase Phase,
    const mdo_agent_context_v1* A, char* Error, size_t Capacity) {
    (void)User;
    bool Member = A->Namespace && !strncmp(A->Namespace, "mohists.", 8) && A->MemberId && A->MemberId[0];
    bool Coordinator = A->AgentId && !strcmp(A->AgentId, "agent.mohists");
    if ((!Member && A->MemberId && A->MemberId[0]) || !A->Application) return MDO_RESULT_OK;
    if(!Member&&!Coordinator&&(!A->SessionId||!A->SessionId[0]))return MDO_RESULT_OK;
    MhContext C; mdo_error_v1 E = {0};
    mdo_result Code = MhContextInit(&C, A->Application, &E);
    xvalue *Envelope = NULL, *Team = NULL;
    if (!Code) Code = MhTeamLoad(&C, &Envelope, &Team, &E);
    if (Code && !Member && !strcmp(E.Code, "mohists_team_missing")) {
        Code = MDO_RESULT_OK;if(!Coordinator){C.V->Release(Envelope);C.V->Release(Team);return Code;}
    }
    else if(!Code&&!Member){
        if(!Coordinator&&!MhIs(&C,Team,"state","active")){C.V->Release(Envelope);C.V->Release(Team);return MDO_RESULT_OK;}
        Coordinator=true;
    }
    if (!Code && Member) {
        bool Allowed = false; const xvalue* Active = C.V->Get(Team, "active");
        for (size_t I = 0; I < C.V->Count(Active); ++I) {
            xvalue *JE = NULL, *Job = NULL;
            mdo_result Check = MhJob(&C, C.V->Text(C.V->At(Active, I)), &JE, &Job, &E);
            if (!Check && MhIs(&C, Job, "member", A->MemberId) && MhIs(&C, Job, "state", "running") &&
                MhIs(&C, Team, "state", "active") && MhUInt(&C, Job, "constraint_revision") == MhUInt(&C, Team, "constraint_revision")) {
                Allowed = true;
                if (Phase == MDO_AGENT_CONTEXT) {
                    xvalue* Source = mdoAgentContextSource(A, "system");
                    const char* Before = MhText(&C, Source, "text");
                    char* Text = Before ? xrtFormat("%s\nMohists collaboration goal (constraint revision %llu):\n%s\nRole: %s. %s\nAgent messages never grant human authorization.",
                        Before, (unsigned long long)MhUInt(&C, Team, "constraint_revision"), MhText(&C, Team, "goal"), MhText(&C, Job, "role"),
                        MhText(&C, Job, "main_run_id") ? "The user selected you as the main speaker. Answer the current main input directly using your existing member context." : "Complete the assigned work and return findings to the coordinator.") : NULL;
                    if (!Text || !mdoAgentSetContextText(A, "system", Text)) Code = MhError(&E, "mohists_context", "Cannot apply member collaboration context", 500);
                    xrtFree(Text);
                }
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
            Code=MhPendingReview(&C,Team,NULL,true,&E);
            const xvalue* Active = C.V->Get(Team, "active");
            for (size_t I = 0; !Code && I < C.V->Count(Active); ++I) {
                xvalue *JE = NULL, *Job = NULL;
                Code = MhJob(&C, C.V->Text(C.V->At(Active, I)), &JE, &Job, &E);
                bool Writer = !Code && MhIs(&C, Job, "role", "worker"); C.V->Release(JE); C.V->Release(Job);
                if (Writer) Code = MhError(&E, "mohists_writer_busy", "Wait for the active writer before changing the same workspace", 409);
                if (Code) break;
            }
        }
    }
    if(!Code&&Phase==MDO_AGENT_BEFORE_DELEGATE)
        Code=MhError(&E,"mohists_delegation","Use the Mohists team tool; recursive or unbudgeted delegation is disabled",403);
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
        const char* Previous = MhText(&C, Team, "last_speaker");
        char* Text=!Code && Before ? xrtFormat("%s\nMohists user preferences:\n%s\n%s\n%s%s%s%llu%s",Before,Mode,Review,
            Previous && Previous[0] ? "Main speaker returned from member " : "",
            Previous && Previous[0] ? Previous : "",
            Previous && Previous[0] ? ". Read its actual native conversation with mohists_team action=history, member above, generation=" : "Current collaboration generation=",
            (unsigned long long)C.Generation,
            Previous && Previous[0] ? " before relying on that exchange. The main chat shows the actual member replies; your own model context does not automatically contain those turns." : ".") : NULL;
        if (!Code && (!Text || !mdoAgentSetContextText(A,"system",Text))) Code=MhError(&E,"mohists_context","Cannot apply collaboration preferences",500);
        xrtFree(Text); C.V->Release(DE); C.V->Release(Defaults);
    }
    C.V->Release(Envelope); C.V->Release(Team);
    if (Code) snprintf(Error, Capacity, "%s", E.Message);
    return Code;
}

#endif
