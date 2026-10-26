/* mdo-command
{"id":"mohists-origin","description":"Check caller provenance","effects":["read"],"requires_session":false,"timeout_ms":30000}
*/
#include "mdo/command.h"
MDO_EXPORT mdo_result mdoCommandRun(const mdo_command_context_v1* C,const xvalue* A,xvalue** R){
    const mdo_sdk_context_v1* S=C->Application; mdo_error_v1 E={0};
    mdo_result Code=mdoCall(S,"sdk.context",NULL,R,&E);
    if(!Code){xvalue* Local=S->Api->Values->UInt(mdoCallOrigin(S));S->Api->Values->Set(*R,"worker_origin",Local);S->Api->Values->Release(Local);}
    return Code;
}
