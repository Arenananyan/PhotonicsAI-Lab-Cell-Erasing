// Password-gated real HTTP LAN origin, isolated from printer/camera/LLM services.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const os=require('node:os');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');

test('phone logs in and creates a chat on a non-secure LAN origin',async t=>{
  const network=os.networkInterfaces();
  const address=(network.en0||Object.values(network).flat()).find(i=>i.family==='IPv4'&&!i.internal)?.address;
  if(!address){t.skip('No LAN address available');return;}
  const root=path.resolve(__dirname,'..');
  const script=`from types import SimpleNamespace
from app import create_app
from werkzeug.serving import make_server
app=create_app(SimpleNamespace(workflow=SimpleNamespace(demo=False),tools=SimpleNamespace(mode='mock')),'browser-test-password')
server=make_server('0.0.0.0',0,app,threaded=True)
print(server.server_port,flush=True)
server.serve_forever()
`;
  const server=spawn(path.join(root,'.venv/bin/python'),['-u','-c',script],{cwd:root,stdio:['ignore','pipe','pipe']});
  t.after(()=>server.kill());
  const port=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('Test server timeout')),10000);
    server.once('error',reject);server.once('exit',code=>reject(Error('Test server exited '+code)));
    server.stdout.once('data',data=>{clearTimeout(timer);resolve(Number(String(data).trim()));});
  });
  const origin=`http://${address}:${port}`;
  assert.equal((await fetch(origin+'/api/config')).status,401);
  const browser=await chromium.launch({headless:true});t.after(()=>browser.close());
  const context=await browser.newContext({viewport:{width:390,height:844},httpCredentials:{username:'lab',password:'browser-test-password'}});
  const page=await context.newPage();const errors=[];let submitted;
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/prepare',async route=>{
    submitted=route.request().postDataJSON();
    await route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({run_id:'phone-test'})});
  });
  await page.route('**/api/runs/phone-test',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({run_id:'phone-test',state:'observed',task:{action:'inspect'},events:[],results:[],queue:[],limits:{},answer_message:'Phone observation test.'})}));
  await page.goto(origin);
  await page.waitForFunction(()=>!document.getElementById('send').disabled);
  assert.equal(await page.evaluate(()=>isSecureContext),false);
  assert.equal(await page.evaluate(()=>typeof crypto.randomUUID),'function');
  await page.locator('#prompt').fill('Inspect the board');await page.locator('#send').click();
  await page.waitForFunction(()=>document.getElementById('assistantMessage')?.textContent.includes('Phone observation test.'));
  assert.match(submitted.chat_id,/^[a-f0-9-]{36}$/);assert.deepEqual(submitted.previous_run_ids,[]);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.deepEqual(errors,[]);
});
