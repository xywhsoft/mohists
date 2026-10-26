// The network peer is a protocol fixture. All business execution uses the
// sole existing native host; no second runtime, accounts or supplier calls.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";

const env=JSON.parse(await readFile(new URL("../runtime/environment.json",import.meta.url),"utf8"));
const {createApplicationClient}=await import(pathToFileURL(`${env.mdo}/app/web/js/api/application.js`));
const {createRemoteTransport}=await import(pathToFileURL(`${env.mdo}/app/web/js/api/remote-transport.js`));
const originalFetch=globalThis.fetch, origin=`http://127.0.0.1:${env.port}`;
const bootstrap=await originalFetch(origin+"/api/v1/bootstrap");
const token=bootstrap.headers.get("X-Mdo-Write-Token");
assert(bootstrap.ok && token);
// Any accidental controller-side business HTTP is a failure. The broker uses
// originalFetch explicitly to stand in for the target device, not as fallback.
globalThis.fetch=()=>{throw Error("Unexpected controller HTTP fallback");};
const forwarded=[], device="d".repeat(32), runtime="e".repeat(32);
const encoder=new TextEncoder(), digest=bytes=>createHash("sha256").update(bytes).digest("hex");

function frame(id,offset,bytes){
 const out=new Uint8Array(29+bytes.length),view=new DataView(out.buffer);
 out.set(encoder.encode("MDP1"));out[4]=2;
 for(let i=0;i<16;i++)out[5+i]=parseInt(id.slice(i*2,i*2+2),16);
 view.setUint32(21,Math.floor(offset/0x100000000));view.setUint32(25,offset>>>0);out.set(bytes,29);
 return out.buffer;
}
class Peer {
 readyState=1; pending=new Map(); failure=null;
 receive(value){if(this.readyState===1)this.onmessage?.({data:value instanceof ArrayBuffer?value:JSON.stringify(value)});}
 send(value){
  if(typeof value==="string"){
   const message=JSON.parse(value);
   if(message.type==="request"){
    const entry={...message,body:new Uint8Array(message.bytes),offset:0};this.pending.set(message.id,entry);
    queueMicrotask(()=>{if(entry.bytes)this.receive({type:"request_ready",id:entry.id,offset:0});else void this.answer(entry);});
   }else if(message.type==="download_ack" || message.type==="cancel"){
    // Responses in this scoped fixture fit one advertised receive window.
   }else throw Error(`Unexpected fixture command ${message.type}`);
  }else{
   const bytes=new Uint8Array(value), view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
   assert.equal(new TextDecoder().decode(bytes.subarray(0,4)),"MDP1");assert.equal(bytes[4],1);
   const id=Buffer.from(bytes.subarray(5,21)).toString("hex"),entry=this.pending.get(id);
   const offset=view.getUint32(21)*0x100000000+view.getUint32(25);
   assert(entry);assert.equal(offset,entry.offset);entry.body.set(bytes.subarray(29),offset);entry.offset+=bytes.length-29;
   queueMicrotask(()=>{
    this.receive({type:"upload_ack",id,offset:entry.offset});
    if(entry.offset===entry.bytes)void this.answer(entry);
   });
  }
 }
 async answer(entry){
  try{
   assert.equal(digest(entry.body),entry.sha256);assert(entry.path.startsWith("/api/v1/"));
   forwarded.push({path:entry.path,body:entry.bytes?JSON.parse(new TextDecoder().decode(entry.body)):null});
   const headers=new Headers(entry.headers);headers.set("Accept-Encoding","identity");
   const response=await originalFetch(origin+entry.path,{method:entry.method,headers,body:entry.bytes?entry.body:undefined});
   const bytes=new Uint8Array(await response.arrayBuffer());assert(bytes.length<=65536,"Fixture response exceeds its single receive window");
   this.receive({type:"response",id:entry.id,status:response.status,headers:[["Content-Type","application/json"],["Content-Length",String(bytes.length)]]});
   for(let at=0;at<bytes.length;at+=16384)this.receive(frame(entry.id,at,bytes.subarray(at,at+16384)));
   this.receive({type:"end",id:entry.id,bytes:bytes.length});this.pending.delete(entry.id);
  }catch(error){this.failure=error;this.onclose?.({code:1006});}
 }
 close(){this.readyState=3;}
}
let peer;
const transport=createRemoteTransport({socket(){return peer=new Peer();}});
async function connect(){
 const ready=transport.connect({origin:"https://fixture.invalid",deviceId:device,mode:"control",ticket:{path:"/api/v1/devices/connect",protocol:"xadmin.device-relay.v1",ticket:"a".repeat(64),payload_limit:262123}});
 peer.receive({type:"ready",version:1,peer_id:"f".repeat(32),device_id:device,mode:"control",payload_limit:262123});
 peer.receive({type:"hello",version:1,runtime_id:runtime,mode:"control",upload_limit:8388608,chunk_limit:65536,window_bytes:65536,live:true,live_limit:2097152});
 await ready;
}
const api={async post(path,body,options={}){
 const response=await transport.fetch("/api/v1"+path,{method:"POST",headers:{"Content-Type":"application/json","X-Mdo-Write-Token":token},body:JSON.stringify(body),signal:options.signal});
 const result=await response.json();
 if(!response.ok)throw Object.assign(Error(result.error?.message),{code:result.error?.code});
 return result;
}};
try{
 await connect();
 let current={project:"mohists"};const sdk=createApplicationClient(()=>current,api);
 const create=()=>sdk.call("session.create",{body:{project_id:"mohists",agent_id:"agent.mohists",model_id:"mohists-local"}});
 const a=(await create()).data.id,b=(await create()).data.id;
 const bound=sdk.bind({project:"mohists",session:a});current={project:"mohists",session:b};
 const team=(action,body={})=>bound.call("mohists.team",{action,...body});
 await team("start",{id:"remote-scope",goal:"Execute only at the owning target and conversation"});
 await team("assign",{id:"seed",member:"scholar",role:"researcher",title:"Remote-owned task",prompt:"Remember the actual owning conversation"});
 assert.equal((await team("execute",{id:"seed"})).state,"succeeded");
 const history=await team("history",{member:"scholar",limit:64});assert(history.items.some(e=>e.kind==="model_text_delta"));
 const before=await team("get");assert.equal(before.calls_used,1);
 await assert.rejects(sdk.call("mohists.team",{action:"get"}),e=>e.code==="mohists_team_missing");
 assert(forwarded.filter(r=>r.body?.method==="mohists.team" && r.body.params.action!=="get").every(r=>r.body.context.session===a));
 const count=forwarded.length;transport.close();
 await assert.rejects(team("assign",{id:"offline",member:"scholar",role:"researcher",title:"Must not start",prompt:"No local fallback"}),e=>e.code==="remote_offline");
 assert.equal(forwarded.length,count);
 await connect();assert.deepEqual(await team("get"),before);
 assert.equal(peer.failure,null);
 console.log("PASS target protocol carries the bound session, actual member history, no offline local fallback and no reconnect replay");
}finally{transport.close();globalThis.fetch=originalFetch;}
