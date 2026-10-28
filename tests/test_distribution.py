"""Ordinary source ZIP and actual current-host native registration; no model call."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid
import zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from package import build, role_header
sys.path.insert(0, str(ROOT.parent / "mdo" / "tests"))
from native_product_runner import product
CONTRACT = r'''
xvalue* QaProductContract(const xvalue* P,xvfs V){
 char E[512]={0};xvalue* R=xrtValueObject();bool H=QaProductHome(SdkField(P,"root"),SdkField(P,"app"),V);
 bool Ok=H&&MdoExtensionsInit()&&MdoApplicationPluginsInit();
 xwork_runtime_config C;xworkRuntimeConfigInit(&C);xwork_error X;xworkErrorInit(&X);xwork_runtime* Runtime=Ok?xworkRuntimeCreate(&C,&X):NULL;
 MdoModuleManagerAttachApplication(MdoApplicationApi());Ok=Ok&&Runtime&&MdoModuleManagerInit(Runtime);
 MdoModuleCatalog* Catalog=Ok?MdoModuleCatalogSnapshot():NULL;
 bool Roles=Catalog&&Catalog->AgentCount==4&&Catalog->ToolCount==2;
 const cstr Ids[]={"agent.mohists","subagent.mohists-researcher","subagent.mohists-worker","subagent.mohists-reviewer"};
 for(size_t J=0;Roles&&J<4;J++){bool Found=false;for(size_t I=0;I<Catalog->AgentCount;I++){MdoModuleAgentBinding* A=Catalog->Agents[I];if(strcmp(A->Id,Ids[J]))continue;
  Found=A->ConfigurationJson&&A->SystemPrompt&&strlen(A->SystemPrompt)>50&&(A->Flags&(J?MDO_AGENT_SUBAGENT:MDO_AGENT_MAIN));
  if(J==1||J==3)Found=Found&&(A->Flags&MDO_AGENT_READ_ONLY)&&!(A->Flags&MDO_AGENT_ALLOW_DELEGATION);
  if(J==0)Found=Found&&(A->Flags&MDO_AGENT_ALLOW_DELEGATION);
 }Roles=Roles&&Found;}
 xrtValueObjectSetNew(R,XRT_STR_LITERAL("roles_and_tools"),xrtValueBool(Roles));
 MdoModuleDiagnostics* D=MdoModuleDiagnosticsSnapshot();xvalue* Messages=xrtValueArray();for(size_t I=0;D&&I<D->Count;I++)xrtValueArrayAppendNew(Messages,xrtValueString(xrtStrView(D->Entries[I].Message)));xrtValueObjectSetNew(R,XRT_STR_LITERAL("diagnostics"),Messages);MdoModuleDiagnosticsRelease(D);
 MdoModuleCatalogRelease(Catalog);MdoModuleManagerUnit();MdoModuleManagerAttachApplication(NULL);MdoApplicationPluginsUnit();if(Runtime)xworkRuntimeRelease(Runtime);MdoExtensionsUnit();if(H)MdoHomeUnit();return R;
}
'''
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--url",default="http://127.0.0.1:58013");parser.add_argument("--home",type=Path,default=ROOT / "runtime/home");parser.add_argument("--project",default="default");args=parser.parse_args()
    output=ROOT / "dist";archive=build(output)[0];first=hashlib.sha256(archive.read_bytes()).hexdigest();assert first==hashlib.sha256(build(output)[0].read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        manifest=json.loads(z.read("extension.json"));recipe=json.loads(z.read("plugin.json"))
        assert manifest["kind"]=="plugins" and manifest["alias"]=="mohists"
        assert set(recipe)=={"entry","exclusive"} and not recipe.get("overrides")
        assert all(p in z.namelist() for p in recipe["entry"].values())
        assert not any(p.startswith(("runtime/",".build/","files/","payload/")) for p in z.namelist())
        assert z.read("runtime-src/roles.inc.h")==role_header()
        out=ROOT / "runtime/acceptance/directory";out.mkdir(parents=True,exist_ok=True)
        fixture=out / ("fixture-"+uuid.uuid4().hex[:12]);directory=fixture / "plugins/mohists";directory.mkdir(parents=True)
        z.extractall(directory)
    try:
        result=product(args,fixture,CONTRACT,out / "native-registration.json")
        assert result.get("roles_and_tools"),result
        (out / "package.json").write_text(json.dumps(dict(sha256=first,bytes=archive.stat().st_size,native=result),ensure_ascii=False,indent=2),encoding="utf-8")
    finally:
        assert fixture.resolve().parent==out.resolve() and fixture.name.startswith("fixture-");shutil.rmtree(fixture)
    print("PASS deterministic whole-directory ZIP, no Home/credentials, four real native roles, two tools; no model call")
if __name__=="__main__":main()
