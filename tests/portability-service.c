/* Test service only; loaded temporarily into the sole development host. */
#include "mdo/sdk.h"
#include "mdo/native/session_backup.h"
#include "mdo/native/session_external.h"
#include "mdo/native/project_lifecycle.h"
#include <string.h>

static bool ProbeCaptureGate(const MdoSessionInfo* Info,void* User,xwork_error* Error) {
    (void)Error;xwork_error Mark;
    *(bool*)User=!MdoSessionExternalStateMark(Info->ProjectId,Info->Id,&Mark)&&Mark.eCode==XWORK_ERROR_CONTEXT;
    return true;
}
static mdo_result Probe(void* User,const mdo_sdk_context_v1* C,const xvalue* P,xvalue** R,mdo_error_v1* E) {
    (void)User;(void)E;const mdo_values_v1* V=C->Api->Values;xwork_error Error;xworkErrorInit(&Error);
    const char* Session=V->Text(V->Get(P,"session"));if(!Session)Session=C->SessionId;
    bool Gate=false,Captured=false;const char* Action=V->Text(V->Get(P,"action"));
    if(Action&&!strcmp(Action,"decode")){
        const char* Document=V->Text(V->Get(P,"document"));
        MdoSessionBackup* Backup=Document?MdoSessionBackupDecode(Document,strlen(Document),NULL,NULL,&Error):NULL;
        Captured=Backup!=NULL;MdoSessionBackupRelease(Backup);
    }else{
        MdoProjectLease* Owner=MdoProjectLeaseAcquire(C->ProjectId,MDO_PROJECT_LEASE_SHARED,&Error);
        if (!Owner) return MDO_RESULT_ERROR;
        if (Action&&!strcmp(Action,"gate")) Captured=MdoSessionWithStoredCapture(C->ProjectId,Session,Owner,ProbeCaptureGate,&Gate,&Error);
        else {
            MdoSessionBackup* Backup=MdoSessionBackupCaptureStored(C->ProjectId,Session,Owner,NULL,&Error);
            Captured=Backup!=NULL;MdoSessionBackupRelease(Backup);
        }
        MdoProjectLeaseRelease(Owner);
    }
    *R=V->Object();xvalue* Value=V->Bool(Captured);V->Set(*R,"captured",Value);V->Release(Value);
    Value=V->Bool(Gate);V->Set(*R,"mark_blocked",Value);V->Release(Value);
    Value=V->String(Error.sMessage);V->Set(*R,"message",Value);V->Release(Value);
    return MDO_RESULT_OK;
}
static mdo_result Register(const mdo_host_services_v1* H,const mdo_registrar_v1* R,void** Data,char* Error,size_t Capacity) {
    (void)H;(void)Data;
    mdo_service_v1 S={sizeof(S),1,"mohists.portability.fixture","Stored capture acceptance","{}","{}",MDO_TOOL_EFFECT_READ,NULL,Probe};
    return R->AddService(R->Context,&S,Error,Capacity);
}
MDO_EXPORT const mdo_module_v1* mdoModuleEntry(void) {
    static const mdo_module_v1 Module={MDO_V1_HEADER(mdo_module_v1),MDO_PLUGIN_ID,"Portability acceptance","Test only",MDO_PLUGIN_VERSION,MDO_CAPABILITY_APPLICATION,NULL,0,Register,NULL};
    return &Module;
}
