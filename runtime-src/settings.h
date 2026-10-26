#ifndef MOHISTS_SETTINGS_H
#define MOHISTS_SETTINGS_H

/* Device-local user defaults, shared by projects. Each team snapshots them so
 * an edit never silently changes a running member's immutable binding. */
static mdo_result MhSettingsLoad(const MhContext* C, xvalue** Envelope, xvalue** Settings, mdo_error_v1* E) {
    mdo_sdk_context_v1 Local = *C->S; Local.ProjectId = "default"; Local.Namespace = "plugin.mohists";
    xvalue* P = C->V->Parse("{\"namespace\":\"plugin.mohists\",\"key\":\"settings\"}");
    mdo_result Code = mdoCall(&Local, "state.get", P, Envelope, E); C->V->Release(P); if (Code) return Code;
    const xvalue* Saved = C->V->Get(*Envelope, "value");
    *Settings = Saved ? C->V->Clone(Saved) : C->V->Parse("{\"schema\":\"mohists.settings.v1\",\"mode\":\"automatic\",\"review\":\"automatic\",\"concurrency\":3,\"max_calls\":24}");
    if (!Saved) {
        xvalue* Roles = C->V->Object();
        for (int I = 0; I < 3; ++I) {
            xvalue* B = C->V->Object(); MhString(C, B, "agent_id", MhAgents[I]); MhString(C, B, "model_id", "");
            MhSet(C, Roles, MhRoles[I], B);
        }
        MhSet(C, *Settings, "roles", Roles);
    }
    return *Settings ? MDO_RESULT_OK : MhError(E, "mohists_memory", "Cannot read settings", 500);
}
static bool MhChoice(const MhContext* C, const xvalue* V, const char* Key, const char* A, const char* B, const char* D) {
    return MhIs(C,V,Key,A) || MhIs(C,V,Key,B) || (D && MhIs(C,V,Key,D));
}
static mdo_result MhBindingsAvailable(MhContext* C, const xvalue* Roles, mdo_error_v1* E) {
    xvalue *Agents=NULL,*Models=NULL;
    mdo_result Code=mdoCall(C->S,"agents.list",NULL,&Agents,E);
    if (!Code) Code=mdoCall(C->S,"models.list",NULL,&Models,E);
    const xvalue* A=C->V->Get(C->V->Get(Agents,"data"),"items");
    const xvalue* M=C->V->Get(C->V->Get(Models,"data"),"models");
    for (size_t I=0; !Code && I<C->V->Count(Roles); ++I) {
        const xvalue* B=C->V->Get(Roles,C->V->Key(Roles,I)); const char* Agent=MhText(C,B,"agent_id"), *Model=MhText(C,B,"model_id");
        bool HasAgent=false,HasModel=!Model||!Model[0];
        for (size_t J=0; J<C->V->Count(A); ++J) if (MhIs(C,C->V->At(A,J),"id",Agent)) HasAgent=true;
        for (size_t J=0; J<C->V->Count(M); ++J) if (Model && MhIs(C,C->V->At(M,J),"id",Model)) HasModel=true;
        if (!HasAgent || !HasModel) Code=MhError(E,"mohists_binding_missing","Select an installed Agent/SubAgent and available model, or leave the model empty to inherit",400);
    }
    C->V->Release(Agents); C->V->Release(Models); return Code;
}
static mdo_result MhSettingsValidate(MhContext* C, const xvalue* Value, xvalue** Clean, mdo_error_v1* E) {
    if (!MhChoice(C,Value,"mode","automatic","requested",NULL) ||
        !MhChoice(C,Value,"review","automatic","always","off") ||
        !MhUInt(C,Value,"concurrency") || MhUInt(C,Value,"concurrency") > 3 ||
        !MhUInt(C,Value,"max_calls") || MhUInt(C,Value,"max_calls") > 128)
        return MhError(E,"mohists_arguments","Supply mode, review, concurrency 1..3 and max_calls 1..128",400);
    const xvalue* Roles = C->V->Get(Value,"roles");
    if (C->V->Kind(Roles) != MDO_VALUE_OBJECT || C->V->Count(Roles) != 3)
        return MhError(E,"mohists_arguments","Configure exactly the three collaboration roles",400);
    for (int I = 0; I < 3; ++I) {
        const xvalue* B = C->V->Get(Roles,MhRoles[I]); const char* A = MhText(C,B,"agent_id"), *M = MhText(C,B,"model_id");
        if (!MhId(A,128) || (M && M[0] && !MhId(M,128)))
            return MhError(E,"mohists_arguments","Role and model bindings need portable identifiers",400);
    }
    mdo_result Available=MhBindingsAvailable(C,Roles,E); if (Available) return Available;
    *Clean = C->V->Object(); MhString(C,*Clean,"schema","mohists.settings.v1");
    const char* Text[] = {"mode","review"};
    for (int I = 0; I < 2; ++I) MhString(C,*Clean,Text[I],MhText(C,Value,Text[I]));
    MhNumber(C,*Clean,"concurrency",MhUInt(C,Value,"concurrency")); MhNumber(C,*Clean,"max_calls",MhUInt(C,Value,"max_calls"));
    xvalue* Bindings = C->V->Object();
    for (int I = 0; I < 3; ++I) {
        const xvalue* B = C->V->Get(Roles,MhRoles[I]); xvalue* Copy = C->V->Object();
        MhString(C,Copy,"agent_id",MhText(C,B,"agent_id")); MhString(C,Copy,"model_id",MhText(C,B,"model_id"));
        MhSet(C,Bindings,MhRoles[I],Copy);
    }
    MhSet(C,*Clean,"roles",Bindings); return MDO_RESULT_OK;
}
static mdo_result MhSettings(void* User, const mdo_sdk_context_v1* S, const xvalue* P, xvalue** R, mdo_error_v1* E) {
    (void)User; MhContext C = {0}; C.S = S; C.V = S->Api->Values;
    const char* Action = MhText(&C,P,"action"); bool Save = Action && !strcmp(Action,"save");
    if (!Action || (!Save && strcmp(Action,"get"))) return MhError(E,"mohists_arguments","Choose get or save",400);
    if (Save && mdoCallOrigin(S) != MDO_ORIGIN_USER) return MhError(E,"mohists_settings_user","Only the user can change collaboration defaults",403);
    xvalue *Envelope = NULL, *Settings = NULL, *Clean = NULL;
    mdo_result Code = MhSettingsLoad(&C,&Envelope,&Settings,E); if (Code) goto done;
    if (Save) {
        Code = MhSettingsValidate(&C,C.V->Get(P,"settings"),&Clean,E); if (Code) goto done;
        mdo_sdk_context_v1 Local = *S; Local.ProjectId = "default";
        xvalue* Q = C.V->Parse("{\"namespace\":\"plugin.mohists\",\"key\":\"settings\"}");
        C.V->Set(Q,"value",Clean); MhNumber(&C,Q,"expected_revision",MhUInt(&C,P,"expected_revision"));
        Code = mdoCall(&Local,"state.compare_exchange",Q,R,E); C.V->Release(Q);
        if (!Code) {
            uint64_t Revision=MhUInt(&C,C.V->At(C.V->Get(*R,"items"),0),"revision");
            C.V->Release(*R); *R=C.V->Object(); C.V->Set(*R,"value",Clean); MhNumber(&C,*R,"revision",Revision);
            MhEmit(&C,"mohists.settings.changed",*R);
        }
    } else {
        *R = C.V->Object(); C.V->Set(*R,"value",Settings); MhNumber(&C,*R,"revision",MhUInt(&C,Envelope,"revision"));
    }
done:
    C.V->Release(Envelope); C.V->Release(Settings); C.V->Release(Clean); return Code;
}

#endif
