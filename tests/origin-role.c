#include "mdo/agent.h"
#include <stdio.h>
#include <string.h>
static mdo_result Drive(void* U,const mdo_agent_context_v1* F,char* Error,size_t N){
    const mdo_sdk_context_v1* C=F->Application;const mdo_values_v1* V=C->Api->Values;
    xvalue *Facts=NULL,*P=NULL,*R=NULL; mdo_error_v1 E={0};mdo_result Code=mdoCall(C,"sdk.context",NULL,&Facts,&E);
    if(Code)goto done;
    P=V->Parse("{\"action\":\"recovery\",\"id\":\"inspect\"}");
    Code=mdoCall(C,"mohists.team",P,&R,&E);V->Release(P);P=NULL;V->Release(R);R=NULL;
    if(Code==MDO_RESULT_OK||strcmp(E.Code,"mohists_recovery_user")){snprintf(Error,N,"Root C Agent was accepted as a user");Code=MDO_RESULT_ERROR;goto done;}
    P=V->Parse("{\"action\":\"message\",\"to\":\"coordinator\",\"message_id\":\"root-c\",\"text\":\"C agent is not human authorization\"}");
    Code=mdoCall(C,"mohists.team",P,&R,&E);V->Release(P);P=NULL;V->Release(R);R=NULL;if(Code)goto done;
    P=V->Parse("{\"method\":\"sdk.context\"}");Code=mdoCall(C,"operation.start",P,&R,&E);V->Release(P);P=NULL;
    if(Code)goto done;
    xvalue* Op=V->Clone(V->Get(R,"id"));V->Release(R);R=NULL;
    P=V->Parse("{\"timeout_ms\":5000}");V->Set(P,"id",Op);Code=mdoCall(C,"operation.wait",P,&R,&E);V->Release(R);R=NULL;
    if(!Code){Code=mdoCall(C,"operation.result",P,&R,&E);if(!Code)V->Set(Facts,"background",R);V->Release(R);R=NULL;}
    if(!Code){Code=mdoCall(C,"operation.release",P,&R,&E);V->Release(R);R=NULL;}
    V->Release(Op);V->Release(P);P=NULL;if(Code)goto done;
    P=V->Parse("{\"namespace\":\"mohists-origin\",\"key\":\"facts\",\"expected_revision\":0}");V->Set(P,"value",Facts);
    xvalue* Namespace=V->String(C->SessionId);V->Set(P,"namespace",Namespace);V->Release(Namespace);
    Code=mdoCall(C,"state.compare_exchange",P,&R,&E);V->Release(P);P=NULL;V->Release(R);R=NULL;
    if(!Code){xwork_error X;Code=mdoAgentRunDefault(F,&X);if(Code)snprintf(Error,N,"%s",X.sMessage);}
done:
    if(Code&&E.Message[0])snprintf(Error,N,"%s",E.Message);V->Release(P);V->Release(R);V->Release(Facts);return Code;
}
static const mdo_agent_program_v1 Program={sizeof(Program),1,NULL,Drive};
static const mdo_agent_v1 Role={.Size=sizeof(Role),.AbiVersion=1,.Id="agent.mohists-origin",.Name="Origin acceptance",
    .Description="Test host provenance for a root C Agent",.SystemPrompt="Reply briefly",.AllowedEffects=MDO_TOOL_EFFECT_READ,
    .Flags=MDO_AGENT_MAIN|MDO_AGENT_READ_ONLY,.Program=&Program};
MDO_AGENT_MODULE(Role)
