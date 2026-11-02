import { test } from "node:test";
import assert from "node:assert/strict";
import { createNewMohistsTask } from "../web/new-session.js";

function fixture() {
  const calls=[], context={projectId:"project",sessionId:"old"};
  const sdk={clientId:"ui-client",context:()=>({...context}),bind(scope){return {call:async(method,p)=>{
    calls.push({method,p,scope});return {data:{id:p.body.client_session_id}};
  }};},async call(method,p){calls.push({method,p});}};
  return {sdk,calls,context};
}
test("new Mohists task creates an empty conversation through public SDK and navigates only this client",async()=>{
  const f=fixture();await createNewMohistsTask(f.sdk,()=>"new-task")();
  assert.deepEqual(f.calls[0],{method:"session.create",scope:{project:"project",session:""},p:{body:{project_id:"project",client_session_id:"new-task",title:"墨者协作",agent_id:"agent.mohists"}}});
  assert.deepEqual(f.calls[1],{method:"ui.invoke",p:{client:"ui-client",action:"ui.navigate",params:{project:"project",session:"new-task"}}});
  assert.equal(f.calls.length,2,"no model call or global settings mutation");
});
test("lost creation reply retries the same identity and concurrent clicks do not create duplicates",async()=>{
  const f=fixture();let attempts=0,release;const scopes=[];
  f.sdk.bind=()=>({async call(m,p){scopes.push(p.body.client_session_id);if(++attempts===1){await new Promise(r=>release=r);throw Error("lost");}return {data:{id:"existing"}};}});
  const start=createNewMohistsTask(f.sdk,()=>"stable");const first=start();await start();release();await assert.rejects(first,/lost/);await start();
  assert.deepEqual(scopes,["stable","stable"]);assert.equal(f.calls[0].p.params.session,"existing");
});
test("a navigation failure reuses the created conversation and a changed page is preserved",async()=>{
  const f=fixture();let attempts=0;f.sdk.call=async()=>{if(++attempts===1)throw Error("navigation lost");};
  const start=createNewMohistsTask(f.sdk,()=>"one");await assert.rejects(start(),/navigation lost/);await start();
  assert.equal(f.calls.filter(x=>x.method==="session.create").length,1);
  const g=fixture();g.sdk.bind=()=>({async call(){g.context.sessionId="other";return {data:{id:"created"}};}});
  await assert.rejects(createNewMohistsTask(g.sdk)(),/当前页面已切换/);assert.equal(g.calls.length,0);
});
