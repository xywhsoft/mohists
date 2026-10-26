#include "mdo/sdk.h"
#include <stdio.h>
#include <string.h>
static mdo_result Route(void* U,const mdo_sdk_context_v1* C,const char* Topic,const xvalue* Input,xvalue** Replacement,mdo_error_v1* E){
    const mdo_values_v1* V=C->Api->Values;const char* Agent=V->Text(V->Get(Input,"agent_id"));
    if(!Agent||strcmp(Agent,"agent.mohists-route"))return MDO_RESULT_OK;
    char Namespace[128];snprintf(Namespace,sizeof(Namespace),"route.%s",C->SessionId);
    xvalue* P=V->Parse("{\"key\":\"off\"}"),*State=NULL,*Name=V->String(Namespace);V->Set(P,"namespace",Name);V->Release(Name);
    mdo_result Code=mdoCall(C,"state.get",P,&State,E);V->Release(P);if(Code)return Code;
    bool Off=false;V->Boolean(V->Get(State,"value"),&Off);V->Release(State);if(Off)return MDO_RESULT_OK;
    *Replacement=V->Clone(Input);xvalue* Target=V->Object();Name=V->String(Namespace);V->Set(Target,"namespace",Name);V->Release(Name);
    Name=V->String("speaker");V->Set(Target,"id",Name);V->Release(Name);
    Name=V->Clone(V->Get(Input,"run_id"));V->Set(Target,"message_id",Name);V->Release(Name);
    V->Set(*Replacement,"route",Target);V->Release(Target);return MDO_RESULT_OK;
}
static mdo_result Register(const mdo_host_services_v1* H,const mdo_registrar_v1* R,void** D,char* E,size_t N){
    mdo_hook_v1 Hook={sizeof(Hook),1,"qa.route","run.route",0,true,NULL,Route};
    return R->AddHook(R->Context,&Hook,E,N);
}
MDO_EXPORT const mdo_module_v1* mdoModuleEntry(void){
    static const mdo_module_v1 M={sizeof(M),1,"qa.route","Route acceptance","Local route acceptance","1.0.0",MDO_CAPABILITY_APPLICATION,NULL,0,Register,NULL};return &M;
}
