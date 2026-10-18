// Run with Node and Playwright. Every API request is intercepted: no hardware is used.
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
let server,browser,origin;
const output=path.join(root,'results','ui-review');
const cell=(id,color,area,x,y)=>({target_id:id,detection_id:id,color,area_mm2:area,printer_coordinates_mm:{x,y}});
const cells=[cell('b1','blue',290,40,170),cell('b2','blue',134,39,35),cell('g1','green',249,132,84)];
function base(state='observed'){
  return {run_id:'ui-test',prompt:'Inspect the cells.',state,events:[],audit:[],results:[],queue:[],limits:{speed_mm_s:20},simulated:true,synthetic_target:true};
}
before(async()=>{
  fs.mkdirSync(output,{recursive:true});
  server=http.createServer((req,res)=>{
    const pathname=new URL(req.url,'http://localhost').pathname;
    const file=pathname==='/'?path.join(root,'templates/index.html'):pathname.startsWith('/static/')?path.join(root,pathname):null;
    if(!file||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    const ext=path.extname(file);res.setHeader('Content-Type',ext==='.html'?'text/html; charset=utf-8':ext==='.js'?'application/javascript; charset=utf-8':ext==='.css'?'text/css':ext==='.gif'?'image/gif':'image/png');
    res.end(ext==='.html'?fs.readFileSync(file,'utf8').replaceAll('{{ home_text }}','209, 208, 100'):fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  origin='http://127.0.0.1:'+server.address().port;
  browser=await chromium.launch({headless:true});
});
after(async()=>{await browser?.close();if(server)await new Promise(resolve=>server.close(resolve));});
async function setup(t,initial,{remembered=false,mobile=false,motion='reduce'}={}){
  const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1000},reducedMotion:motion});
  t.after(()=>context.close());
  await context.addInitScript(({remembered})=>{if(sessionStorage.getItem('uiTestInitialized'))return;sessionStorage.setItem('uiTestInitialized','1');localStorage.clear();localStorage.setItem('labLanguage','en');if(remembered)localStorage.setItem('labRunId','ui-test');},{remembered});
  const page=await context.newPage();const errors=[],posts=[],mascotRequests=[];let data=initial;
  page.on('request',request=>{if(request.url().includes('/static/mascot/'))mascotRequests.push(request.url().split('/').at(-1));});
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',async route=>{
    const req=route.request(),url=new URL(req.url()),body=req.method()==='POST'?req.postDataJSON():null;
    let reply={},status=200;
    if(body!==null){posts.push({path:url.pathname,body,headers:req.headers()});assert.equal(req.headers()['x-lab-control'],'local');}
    if(url.pathname==='/api/config')reply={printer_mode:'mock',demo:true,motion_enabled:true};
    else if(url.pathname==='/api/prepare'){reply={run_id:'ui-test'};status=202;}
    else if(url.pathname==='/api/runs/ui-test')reply=data;
    else if(url.pathname.endsWith('/execute')){data={...data,state:'executing',authorization:{id:'approved'},audit:[{kind:'tool_request',name:'execute_sequence'}]};reply={ok:true};status=202;}
    else if(url.pathname.endsWith('/answer')){data={...data,state:'observed',answer_message:'Answer received.'};reply={ok:true};status=202;}
    else if(url.pathname.endsWith('/cancel')){data={...data,state:'cancelled'};reply={ok:true};}
    else if(url.pathname.endsWith('/stop-task')){data={...data,stop_requested:true};reply={ok:true};}
    else if(url.pathname==='/api/stop'){data={...data,state:'stopped',stop_requested:true};reply={ok:true};}
    else if(url.pathname==='/api/simulation/reset')reply={ok:true,simulated:true};
    else if(url.pathname.includes('/evidence/')||url.pathname.endsWith('/image')||url.pathname.endsWith('/observation/board')||url.pathname.includes('/observation/cells/')){
      await route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="300"><rect width="600" height="300" fill="#e5efdf"/><circle cx="300" cy="150" r="60" fill="#68b848"/></svg>'});return;
    }else {reply={error:'Unknown run'};status=409;}
    await route.fulfill({status,contentType:'application/json',body:JSON.stringify(reply)});
  });
  await page.goto(origin);
  await page.waitForFunction(()=>document.getElementById('modeText').textContent==='Synthetic simulation');
  const send=async(text='Inspect the cells.')=>{await page.locator('#prompt').fill(text);await page.locator('#send').click();await page.locator('#assistantMessage').waitFor();};
  return {page,posts,errors,send,mascotRequests,setData:value=>data=value};
}
test('supplied design, language switch, and mobile layout',async t=>{
  const {page,errors}=await setup(t,base(),{mobile:true});
  assert.equal(await page.locator('#emptyState').isVisible(),true);
  await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.locator('#language').click();
  assert.equal(await page.locator('html').getAttribute('lang'),'hy');
  assert.match(await page.locator('h1').innerText(),/բջիջ/);
  await page.locator('#openSidebar').click();
  assert.equal(await page.locator('#sidebar').evaluate(node=>node.inert),false);
  await page.locator('#closeSidebar').click();
  assert.equal(await page.locator('#sidebar').evaluate(node=>node.inert),true);
  assert.deepEqual(errors,[]);
});
test('rankings stay grouped; suggestions fill without dispatch',async t=>{
  const data={...base(),answer_message:'Three measured cells.',ranked_cells:cells,suggestions:[{label:'Clean largest blue',prompt:'Clean the largest blue cell.'}],suggestion_reason:'Blue has the largest measured region.'};
  const {page,posts,errors,send}=await setup(t,data);
  await send();await page.locator('[data-suggestion]').waitFor();
  await page.waitForFunction(()=>!document.getElementById('resetSimulation').disabled);
  const groups=page.locator('.ranked-group');assert.equal(await groups.count(),2);
  assert.match(await groups.nth(0).innerText(),/290.*\n.*134/s);
  assert.match(await groups.nth(1).innerText(),/249/);
  await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
  await page.locator('[data-suggestion]').click();
  assert.equal(await page.locator('#prompt').inputValue(),'Clean the largest blue cell.');
  assert.equal(posts.length,1);assert.equal(posts[0].path,'/api/prepare');
  assert.equal(await page.locator('#approve').count(),0);
  assert.deepEqual(errors,[]);
});
test('exact path approval stays gated; queue, speed, and condition remain visible',async t=>{
  const data={...base('awaiting_confirmation'),phase:'wipe',task:{action:'wipe',selection:'largest',color:'blue',message:'Clean largest blue',condition:{metric:'blue_count',operator:'gt',value:1,compare_metric:null}},condition_result:{passed:true,left:2,right:1},queue:[cells[0]],current_target_id:'b1',plan:{start:[209,208,100],waypoints:[[40,170,100],[40,170,14.5],[40,180,14.5],[209,208,100]]},preview:{token:'test-token'},limits:{speed_mm_s:15}};
  const {page,posts,errors,send}=await setup(t,data);await send('If blue count is above one, clean largest blue');
  await page.locator('#approve').waitFor();assert.equal(await page.locator('#approve').isDisabled(),true);
  assert.equal(posts.length,1);assert.match(await page.locator('#conditionHost').innerText(),/2 > 1/);
  assert.match(await page.locator('#queueHost').innerText(),/Current/);assert.match(await page.locator('#approvalHost').innerText(),/15 mm\/s/);
  await page.locator('.path-details summary').click();assert.equal(await page.locator('tbody tr').count(),4);
  await page.locator('#approve').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,'approval.png'),fullPage:true});
  assert.equal(await page.locator('#newCommand').isDisabled(),true);
  assert.equal(await page.locator('.delete-chat').first().isDisabled(),true);
  await page.locator('#clearPath').check();await page.locator('#approve').click();
  await page.locator('.execution').waitFor();assert.equal(posts.filter(p=>p.path.endsWith('/execute')).length,1);
  assert.deepEqual(posts.find(p=>p.path.endsWith('/execute')).body,{confirmed:true,clear_path:true});
  assert.equal(await page.locator('#approve').count(),0);
  await page.locator('#stopTask').click();assert.equal(posts.filter(p=>p.path.endsWith('/stop-task')).length,1);
  assert.deepEqual(errors,[]);
});
test('unmet condition reports without any motion controls or requests',async t=>{
  const data={...base(),task:{action:'wipe',condition:{metric:'blue_count',operator:'gt',value:5,compare_metric:null}},condition_result:{passed:false,left:3,right:5},answer_message:'Condition not met. No movement.'};
  const {page,posts,errors,send}=await setup(t,data);await send('If blue count is above five, clean smallest green');
  await page.locator('.condition-result.unmet').waitFor();assert.equal(await page.locator('#approve').count(),0);
  assert.deepEqual(posts.map(p=>p.path),['/api/prepare']);assert.deepEqual(errors,[]);
});
test('clarification uses the answer endpoint and supports cancellation',async t=>{
  const data={...base('awaiting_answer'),question:'Which color?'};
  const {page,posts,errors,send,setData}=await setup(t,data);await send('Clean a cell');
  await page.locator('.question').waitFor();await page.waitForFunction(()=>!document.getElementById('send').disabled);
  await send('Blue');await page.waitForFunction(()=>document.getElementById('assistantMessage').textContent==='Answer received.');
  assert.equal(posts.filter(p=>p.path.endsWith('/answer')).length,1);
  assert.deepEqual(posts.find(p=>p.path.endsWith('/answer')).body,{answer:'Blue'});
  setData(data);await page.locator('#newCommand').click();await send('Clean another cell');await page.locator('#cancelQuestion').waitFor();
  await page.locator('#cancelQuestion').click();await page.waitForFunction(()=>document.getElementById('newCommand').disabled===false);
  assert.equal(posts.filter(p=>p.path.endsWith('/cancel')).length,1);assert.deepEqual(errors,[]);
});
test('previous dashboard run restores without losing pending approval',async t=>{
  const data={...base('awaiting_confirmation'),task:{action:'home'},phase:'task',plan:{start:[20,30,40],waypoints:[[20,30,100],[209,30,100],[209,208,100]]},preview:{token:'old-session'}};
  const {page,posts,errors}=await setup(t,data,{remembered:true});
  await page.locator('#approve').waitFor();assert.equal(await page.locator('#approve').isDisabled(),true);assert.equal(posts.length,0);
  await page.reload();await page.locator('#approve').waitFor();assert.equal(await page.locator('#approve').isDisabled(),true);
  assert.deepEqual(errors,[]);
});
test('evidence comparison and emergency shutdown remain separate controls',async t=>{
  const data={...base('completed'),results:[{target_id:'b1',verdict:'clean',assessment:{message:'Measured residue is low.'},evidence:{images:['before','after'],remaining_fraction:.02}}],verification:{position_mm:{x:209,y:208,z:100}}};
  const {page,posts,errors,send}=await setup(t,data);await send('Clean largest blue');
  await page.locator('.comparison').waitFor();assert.match(await page.locator('#assistantMessage').innerText(),/X 209/);
  await page.locator('.evidence-zoom').first().click();assert.equal(await page.locator('#lightbox').isVisible(),true);
  await page.locator('#closeLightbox').click();await page.locator('#emergency').click();assert.equal(await page.locator('#confirmDialog').isVisible(),true);
  assert.equal(posts.length,1);await page.locator('#confirmEmergency').click();
  await page.waitForFunction(()=>!document.getElementById('confirmDialog').open);
  assert.equal(posts.filter(p=>p.path==='/api/stop').length,1);assert.deepEqual(errors,[]);
});
test('emergency action remains available while a normal request is pending',async t=>{
  const {page,posts,errors}=await setup(t,base('preparing'));
  let release,entered;
  const pending=new Promise(resolve=>entered=resolve);
  const gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/prepare',async route=>{entered();await gate;await route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({run_id:'ui-test'})});});
  await page.locator('#prompt').fill('Inspect the cells.');await page.locator('#send').click();await pending;
  assert.equal(await page.locator('#send').isDisabled(),true);
  await page.locator('#emergency').click();await page.locator('#confirmEmergency').click();
  await page.waitForFunction(()=>!document.getElementById('confirmDialog').open);
  assert.equal(posts.filter(p=>p.path==='/api/stop').length,1);
  release();assert.deepEqual(errors,[]);
});
test('preparing and movement commands do not invent camera scanning',async t=>{
  for(const action of [null,'move','home']) {
    const data={...base('preparing'),task:action?{action,message:'Preparing the requested movement.'}:null};
    const {page,errors,send}=await setup(t,data);
    await send('Go home');await page.waitForFunction(()=>document.getElementById('send').disabled);
    assert.equal(await page.locator('.image-stage').count(),0);
    assert.doesNotMatch(await page.locator('#assistantMessage').innerText(),/camera|scanning/i);
    assert.doesNotMatch(await page.locator('.reason-label').innerText(),/scanning/i);
    assert.deepEqual(errors,[]);
  }
});
test('commands form one persistent chat ribbon until New chat is selected',async t=>{
  const {page,posts,errors,send,setData}=await setup(t,{...base(),answer_message:'First measured answer.'});
  await send('How many cells?');await page.waitForFunction(()=>!document.getElementById('send').disabled);
  setData({...base(),answer_message:'Second measured answer.'});await send('Where is the head?');
  await page.waitForFunction(()=>!document.getElementById('send').disabled);
  assert.equal(await page.locator('.user-message').count(),2);
  assert.equal(await page.locator('.assistant-turn').count(),2);
  assert.equal(await page.locator('.history-item').count(),1);
  assert.match(await page.locator('#turns').innerText(),/First measured answer/);
  assert.match(await page.locator('#turns').innerText(),/Second measured answer/);
  assert.equal(await page.locator('#assistantMessage').count(),1);
  await page.locator('#resetSimulation').click();
  await page.waitForFunction(()=>!document.getElementById('send').disabled);
  assert.equal(await page.locator('.assistant-turn').count(),2);assert.equal(await page.locator('.history-item').count(),1);
  await page.reload();await page.locator('#assistantMessage').waitFor();
  assert.equal(await page.locator('.assistant-turn').count(),2);
  assert.match(await page.locator('#turns').innerText(),/First measured answer/);
  await page.screenshot({path:path.join(output,'chat-ribbon.png'),fullPage:true});
  await page.locator('#language').click();assert.equal(await page.locator('.assistant-turn').count(),2);
  await page.locator('#newCommand').click();assert.equal(await page.locator('#emptyState').isVisible(),true);
  setData({...base(),answer_message:'A different chat.'});await send('Start a different chat');
  await page.waitForFunction(()=>!document.getElementById('send').disabled);
  assert.equal(await page.locator('.assistant-turn').count(),1);assert.equal(await page.locator('.history-item').count(),2);
  await page.locator('.history-item').nth(1).click();await page.waitForFunction(()=>document.querySelectorAll('.assistant-turn').length===2);
  assert.equal(posts.filter(post=>post.path==='/api/prepare').length,3);
  assert.equal(posts.filter(post=>post.path.endsWith('/execute')).length,0);assert.deepEqual(errors,[]);
});
test('past paths remain read only and cannot approve the next command',async t=>{
  const plan={start:[209,208,100],waypoints:[[40,208,100],[40,50,100]]};
  const done={...base('completed'),task:{action:'move',message:'Movement finished'},plan,verification:{position_mm:{x:40,y:50,z:100}}};
  const {page,posts,errors,send,setData}=await setup(t,done);
  await send('Go to X40 Y50 Z100');await page.waitForFunction(()=>!document.getElementById('send').disabled);
  setData({...base('awaiting_confirmation'),task:{action:'home',message:'Review home'},plan,preview:{token:'next'}});
  await send('Return home');await page.locator('#approve').waitFor();
  assert.equal(await page.locator('.assistant-turn').count(),2);
  assert.equal(await page.locator('#approve').count(),1);
  assert.equal(await page.locator('.past-turn .clearance').count(),0);
  assert.equal(await page.locator('.past-turn .path-details').count(),1);
  assert.equal(await page.locator('#approve').isDisabled(),true);
  assert.equal(posts.filter(post=>post.path.endsWith('/execute')).length,0);assert.deepEqual(errors,[]);
});
test('a captured annotated target still displays its actual image',async t=>{
  const data={...base('awaiting_confirmation'),task:{action:'wipe'},target:{...cells[0],frame_id:'captured-frame',annotated_image:'/captured.png'}};
  const {page,posts,errors,send}=await setup(t,data);await send('Clean largest blue');
  await page.locator('.image-stage.loaded').waitFor();
  assert.equal(await page.locator('.cv-image').isVisible(),true);
  assert.match(await page.locator('.cv-image').getAttribute('src'),/\/api\/runs\/ui-test\/image/);
  assert.equal(posts.filter(post=>post.path.endsWith('/execute')).length,0);assert.deepEqual(errors,[]);
});
test('deleting the open chat requires confirmation and persists across reload',async t=>{
  const {page,posts,errors,send}=await setup(t,{...base(),answer_message:'Saved answer.'});
  await send('My saved conversation');await page.waitForFunction(()=>!document.getElementById('send').disabled);
  await page.locator('.delete-chat').click();assert.equal(await page.locator('#deleteChatDialog').isVisible(),true);
  assert.equal(await page.locator('#deleteChatName').innerText(),'My saved conversation');
  await page.locator('#cancelDeleteChat').click();assert.equal(await page.locator('.history-item').count(),1);
  await page.locator('.delete-chat').click();await page.locator('#confirmDeleteChat').click();
  assert.equal(await page.locator('.history-item').count(),0);assert.equal(await page.locator('#emptyState').isVisible(),true);
  assert.equal(await page.evaluate(()=>localStorage.getItem('labRunId')),null);
  assert.deepEqual(await page.evaluate(()=>JSON.parse(localStorage.getItem('lab.command.history.v1'))),[]);
  await page.reload();await page.waitForFunction(()=>!document.getElementById('send').disabled);
  assert.equal(await page.locator('.history-item').count(),0);assert.equal(await page.locator('#emptyState').isVisible(),true);
  assert.deepEqual(posts.map(post=>post.path),['/api/prepare']);assert.deepEqual(errors,[]);
});
test('deleting a different chat preserves the current conversation',async t=>{
  const {page,posts,errors,send,setData}=await setup(t,{...base(),answer_message:'First chat answer.'});
  await send('First chat');await page.waitForFunction(()=>!document.getElementById('send').disabled);
  await page.locator('#newCommand').click();setData({...base(),answer_message:'Second chat answer.'});
  await send('Second chat');await page.waitForFunction(()=>!document.getElementById('send').disabled);
  await page.locator('.delete-chat').nth(1).click();await page.locator('#confirmDeleteChat').click();
  assert.equal(await page.locator('.history-item').count(),1);
  assert.match(await page.locator('#turns').innerText(),/Second chat answer/);
  assert.equal(await page.locator('#emptyState').isVisible(),false);
  assert.equal(await page.locator('#send').isDisabled(),false);
  assert.deepEqual(posts.map(post=>post.path),['/api/prepare','/api/prepare']);assert.deepEqual(errors,[]);
});
test('observation shows the full board and matching individual cells in ranked order',async t=>{
  const data={...base(),answer_message:'Three cells from the captured frame.',
    observation_images:{frame_id:'saved-board-frame',acquired_at:'2026-10-17T10:00:00Z',board_image:'board.png',cells:[]},
    ranked_cells:cells.map((cell,index)=>({...cell,image_index:[1,0,2][index],display_number:[7,2,4][index]}))};
  const {page,posts,errors,send,setData}=await setup(t,data);await send('Count and rank the cells');
  await page.locator('.board-observation .image-stage.loaded').waitFor();
  assert.equal(await page.locator('.cell-image').count(),3);
  assert.match(await page.locator('.board-observation').innerText(),/saved-board-frame/);
  assert.match(await page.locator('.cell-image').nth(0).locator('img').getAttribute('src'),/cells\/1$/);
  assert.match(await page.locator('.cell-image').nth(1).locator('img').getAttribute('src'),/cells\/0$/);
  assert.equal(await page.locator('.cell-image').first().locator('.cell-number').innerText(),'#7');
  await page.locator('.cell-image').first().click();assert.match(await page.locator('#zoomImage').getAttribute('src'),/cells\/1$/);
  await page.locator('#closeLightbox').click();await page.locator('.board-observation img').click();
  assert.match(await page.locator('#zoomImage').getAttribute('src'),/observation\/board$/);await page.locator('#closeLightbox').click();
  await page.locator('.ranked-group').first().scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,'board-and-cells.png'),fullPage:true});
  setData({...base('completed'),task:{action:'move'}});await send('Go to X40 Y50 Z100');
  await page.waitForFunction(()=>!document.getElementById('send').disabled);
  assert.equal(await page.locator('.past-turn .board-observation').count(),1);
  assert.equal(await page.locator('#boardHost .board-observation').count(),0);
  await page.reload();await page.locator('#assistantMessage').waitFor();
  assert.equal(await page.locator('.past-turn .cell-image').count(),3);
  assert.equal(posts.filter(post=>post.path.endsWith('/execute')).length,0);assert.deepEqual(errors,[]);
});
test('unavailable observation pictures remain explicit without hiding measurements',async t=>{
  const {page,errors,send}=await setup(t,{...base(),answer_message:'Three measured cells.',ranked_cells:cells,observation_image_warning:'Saved observation image unavailable'});
  await send();await page.locator('.ranked-group').first().waitFor();
  assert.match(await page.locator('#boardHost').innerText(),/unavailable/i);
  assert.equal(await page.locator('.board-observation').count(),0);
  assert.equal(await page.locator('.cell-image').count(),0);assert.deepEqual(errors,[]);
});
test('distance report persists and home observation waits for approval',async t=>{
  const d={from_target_id:'g1',to_target_id:'b1',from_xy_mm:[132,84],to_xy_mm:[40,170],distance_mm:125.93649,frame_id:'f'};
  const {page,posts,errors,send,setData}=await setup(t,{...base(),task:{action:'inspect'},distances:[d],answer_message:'Measured center distance.'});
  await send('Measure the distance');await page.locator('#insightsHost strong').waitFor();
  assert.match(await page.locator('#insightsHost').innerText(),/125.94 mm/);
  await page.reload();await page.locator('#insightsHost strong').waitFor();
  assert.match(await page.locator('#insightsHost').innerText(),/Center-to-center/);
  setData({...base('awaiting_confirmation'),phase:'observe_home',task:{action:'inspect',observe_from_home:true},plan:{start:[40,50,100],waypoints:[[209,50,100],[209,208,100]]},preview:{token:'home'}});
  await send('Go home then inspect');await page.locator('#approve').waitFor();
  assert.match(await page.locator('#approvalHost').innerText(),/Review the home path/);
  assert.equal(await page.locator('#approve').isDisabled(),true);
  assert.equal(posts.filter(p=>p.path.endsWith('/execute')).length,0);
  assert.deepEqual(errors,[]);
});
test('server receives the current chat identity and prior run references',async t=>{
  const target={...cells[2],frame_id:'measured',calibration_id:'cal'};
  const {page,posts,errors,send,setData}=await setup(t,{...base(),selected_targets:[target],answer_message:'Largest green cell.'});
  await send('find biggest green');await page.waitForFunction(()=>!document.getElementById('send').disabled);
  assert.match(await page.locator('#insightsHost').innerText(),/Selected cell/);
  const first=posts.find(p=>p.path==='/api/prepare');assert.ok(first.body.chat_id);assert.deepEqual(first.body.previous_run_ids,[]);
  setData({...base(),answer_message:'Remembered target.'});await send('describe that point');
  await page.waitForFunction(()=>!document.getElementById('send').disabled);
  const prepares=posts.filter(p=>p.path==='/api/prepare');
  assert.equal(prepares[1].body.chat_id,first.body.chat_id);assert.deepEqual(prepares[1].body.previous_run_ids,['ui-test']);
  await page.locator('#newCommand').click();await send('new conversation');
  const last=posts.filter(p=>p.path==='/api/prepare').at(-1);
  assert.notEqual(last.body.chat_id,first.body.chat_id);assert.deepEqual(last.body.previous_run_ids,[]);
  assert.deepEqual(errors,[]);
});

const mascotState=(page,state)=>page.waitForFunction(state=>{
  const host=document.querySelector('photonics-mascot'),img=host.querySelector('img');
  return host.dataset.animation===state&&img.complete&&img.naturalWidth===256;
},state);
async function mascotNoOverlap(page){
  const mascot=await page.locator('photonics-mascot').boundingBox();
  for(const selector of ['#prompt','#send','.topbar','#sidebar:not([inert])']){
    const locator=page.locator(selector);
    if(!await locator.count()||!await locator.isVisible())continue;
    const box=await locator.boundingBox();
    assert.ok(!(mascot.x<box.x+box.width&&mascot.x+mascot.width>box.x&&mascot.y<box.y+box.height&&mascot.y+mascot.height>box.y),'Mascot overlaps '+selector);
  }
  assert.ok(mascot.x>=0&&mascot.y>=0);
  const composer=await page.locator('#composer').boundingBox();
  const image=await page.locator('.mascot-image').boundingBox();
  assert.ok(Math.abs(image.y+image.height*(216/256)-composer.y)<2,'Feet should stand on the composer border');
  assert.ok(image.x>=composer.x&&image.x+image.width<=composer.x+composer.width);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
}
test('mascot restarts gestures, supports keyboard, and pauses persistently',async t=>{
  const {page,errors,posts,mascotRequests}=await setup(t,base(),{motion:'no-preference'});
  await mascotState(page,'idle');
  assert.deepEqual(mascotRequests,['photonics-ai-idle-256.gif']);
  const trigger=page.locator('.mascot-trigger');
  await trigger.hover();await mascotState(page,'wave');
  const first=await page.locator('.mascot-image').getAttribute('src');
  await page.mouse.move(1,1);await trigger.hover();await mascotState(page,'wave');
  assert.notEqual(await page.locator('.mascot-image').getAttribute('src'),first);
  await mascotState(page,'idle');
  await trigger.focus();await mascotState(page,'wave');
  await page.keyboard.press('Enter');await mascotState(page,'hop');
  await mascotState(page,'idle');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Space');await mascotState(page,'hop');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('.mascot-pause').evaluate(node=>node===document.activeElement),true);
  await page.keyboard.press('Enter');await mascotState(page,'poster');
  assert.equal(await page.locator('.mascot-pause').getAttribute('aria-pressed'),'true');
  await trigger.click();await mascotState(page,'poster');
  await page.keyboard.press('Escape');
  await page.reload();await mascotState(page,'poster');
  await trigger.hover();await page.getByRole('button',{name:'Resume mascot animation',exact:true}).click();await mascotState(page,'idle');
  assert.equal(mascotRequests.filter(name=>name==='photonics-ai-wave-256.gif').length,1);
  assert.equal(mascotRequests.filter(name=>name==='photonics-ai-hop-256.gif').length,1);
  assert.ok(!mascotRequests.includes('photonics-ai-scanning-256.gif'));
  assert.equal(await page.locator('.mascot-image').getAttribute('alt'),'');
  assert.equal(posts.length,0);assert.deepEqual(errors,[]);
});
test('mascot uses actual workflow activity and honors pause and motion changes',async t=>{
  const {page,errors,send,setData}=await setup(t,base('scanning'),{motion:'no-preference'});
  await send();await mascotState(page,'scanning');
  await page.locator('.mascot-trigger').hover();
  await page.getByRole('button',{name:'Pause mascot animation',exact:true}).click();await mascotState(page,'poster');
  await page.getByRole('button',{name:'Resume mascot animation',exact:true}).click();await mascotState(page,'scanning');
  setData(base('awaiting_confirmation'));await mascotState(page,'idle');
  await page.emulateMedia({reducedMotion:'reduce'});await mascotState(page,'poster');
  assert.equal(await page.locator('.mascot-pause').isDisabled(),true);
  await page.locator('.mascot-trigger').click();await mascotState(page,'poster');
  await page.keyboard.press('Escape');
  await page.emulateMedia({reducedMotion:'no-preference'});await mascotState(page,'idle');
  await page.locator('#language').click();
  assert.match(await page.locator('.mascot-trigger').getAttribute('aria-label'),/օգնական/);
  assert.deepEqual(errors,[]);
});
test('reduced-motion loads only the static poster; component disconnect clears work',async t=>{
  const {page,errors,mascotRequests}=await setup(t,base());
  await mascotState(page,'poster');
  await page.locator('.mascot-trigger').focus();await page.keyboard.press('Enter');
  await page.keyboard.press('Escape');
  assert.deepEqual(mascotRequests,['photonics-ai-poster-256.png']);
  await page.emulateMedia({reducedMotion:'no-preference'});await mascotState(page,'idle');
  await page.locator('.mascot-trigger').click();await mascotState(page,'hop');
  const cleanup=await page.evaluate(()=>{
    const host=document.querySelector('photonics-mascot');
    host.remove();return {aborted:host._lifecycle.signal.aborted,url:host._url,timer:host._timer};
  });
  assert.deepEqual(cleanup,{aborted:true,url:null,timer:null});assert.deepEqual(errors,[]);
});
for(const mobile of [false,true])test(`mascot layout on ${mobile?'mobile':'desktop'} in light and dark themes`,async t=>{
  const {page,errors}=await setup(t,base(),{mobile});await mascotState(page,'poster');
  const image=await page.locator('.mascot-image').boundingBox();
  assert.equal(image.width,mobile?48:64);assert.equal(image.height,image.width);
  assert.equal(await page.locator('.mascot-image').evaluate(node=>getComputedStyle(node).imageRendering),'pixelated');
  for(const dark of [false,true]){
    if(dark)await page.locator('#themeToggle').click();
    // The existing theme transition lasts 420 ms, even under reduced motion.
    await page.evaluate(()=>Promise.all(document.getAnimations().filter(animation=>animation.effect?.getComputedTiming().iterations!==Infinity).map(animation=>animation.finished.catch(()=>{}))));
    await mascotNoOverlap(page);
    await page.screenshot({path:path.join(output,`mascot-${mobile?'mobile':'desktop'}-${dark?'dark':'light'}.png`),fullPage:true});
  }
  await page.locator('#prompt').fill('A multiline instruction\n'.repeat(6));
  await mascotNoOverlap(page);
  await page.evaluate(()=>{const notice=document.getElementById('notice');notice.hidden=false;notice.textContent='This run is no longer available. Start a new command to continue.';});
  const noticeBox=await page.locator('#notice').boundingBox(),composerBox=await page.locator('#composer').boundingBox();
  assert.ok(noticeBox.y>=composerBox.y+composerBox.height,'Notification should stay below the composer and mascot');
  assert.ok(await page.locator('.composer-dock').evaluate(node=>parseFloat(getComputedStyle(node).paddingTop)<=20),'No full-height mascot spacer');
  await page.screenshot({path:path.join(output,`mascot-${mobile?'mobile':'desktop'}-notice.png`),fullPage:true});
  await page.locator('#emergency').click();
  assert.equal(await page.locator('#confirmDialog').isVisible(),true);
  assert.equal(await page.locator('.mascot-trigger').evaluate(node=>node.matches(':focus')),false);
  await page.locator('#dismissConfirm').click();
  if(mobile){
    await page.locator('#openSidebar').click();
    assert.equal(await page.locator('.workspace').evaluate(node=>node.inert),true);
    await page.locator('#closeSidebar').click();
    await page.setViewportSize({width:320,height:640});await mascotNoOverlap(page);
  }
  assert.deepEqual(errors,[]);
});

test('mascot panel submits questions to the shared conversation and preserves drafts',async t=>{
  const {page,errors,posts}=await setup(t,{...base(),answer_message:'The printer is simulated and stationary.'});
  await page.locator('#prompt').fill('What is the printer status?');
  await page.locator('.mascot-trigger').click();
  assert.equal(await page.locator('.mascot-question-form textarea').inputValue(),'What is the printer status?');
  assert.match(await page.locator('.mascot-panel-status').innerText(),/Demo mode/);
  await page.locator('.mascot-question-form textarea').fill('Where is the print head?');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#prompt').inputValue(),'Where is the print head?');
  assert.equal(await page.locator('.mascot-trigger').getAttribute('aria-expanded'),'false');
  await page.locator('.mascot-trigger').click();
  await page.locator('.mascot-question-form textarea').press('Enter');
  await page.locator('#assistantMessage').waitFor();
  assert.match(await page.locator('#assistantMessage').innerText(),/stationary/);
  assert.equal(posts.length,1);assert.equal(posts[0].path,'/api/prepare');
  assert.equal(posts[0].body.prompt,'Where is the print head?');
  assert.equal(await page.locator('.mascot-panel').evaluate(node=>node.matches(':popover-open')),false);
  assert.deepEqual(errors,[]);
});
test('mascot shortcuts only fill a draft; motion still needs the existing approval',async t=>{
  const data={...base('awaiting_confirmation'),task:{action:'wipe',color:'blue',selection:'largest'},plan:{start:[209,208,100],waypoints:[[40,170,100],[209,208,100]]},preview:{token:'test-token'},target:cells[0]};
  const {page,errors,posts}=await setup(t,data);
  await page.locator('.mascot-trigger').click();
  await page.locator('[data-command="Clean the largest blue cell."]').click();
  assert.equal(posts.length,0);
  assert.equal(await page.locator('#prompt').inputValue(),'Clean the largest blue cell.');
  await page.locator('.mascot-question-form [type="submit"]').click();
  await page.locator('#approve').waitFor();
  assert.equal(await page.locator('#approve').isDisabled(),true);
  assert.equal(posts.length,1);
  await page.locator('.mascot-trigger').click();
  assert.equal(await page.locator('.mascot-question-form [type="submit"]').isDisabled(),true);
  assert.match(await page.locator('.mascot-panel-status').innerText(),/Finish or cancel/);
  assert.equal(posts.filter(post=>post.path.endsWith('/execute')).length,0);
  assert.deepEqual(errors,[]);
});
test('mascot panel sends clarification replies to the existing answer endpoint',async t=>{
  const {page,errors,posts,send}=await setup(t,{...base('awaiting_answer'),question:'Which color?'});
  await send('Clean a cell.');await page.locator('.mascot-trigger').click();
  assert.equal(await page.locator('.mascot-shortcuts button:visible').count(),0);
  await page.locator('.mascot-question-form textarea').fill('Blue.');
  await page.locator('.mascot-question-form [type="submit"]').click();
  await page.waitForFunction(()=>document.getElementById('assistantMessage').textContent==='Answer received.');
  assert.deepEqual(posts.map(post=>post.path),['/api/prepare','/api/runs/ui-test/answer']);
  assert.equal(posts[1].body.answer,'Blue.');assert.deepEqual(errors,[]);
});
for(const mobile of [false,true])test(`mascot assistant panel fits ${mobile?'mobile':'desktop'} and both themes`,async t=>{
  const {page,errors}=await setup(t,base(),{mobile});
  for(const dark of [false,true]){
    if(dark)await page.locator('#themeToggle').click();
    await page.locator('.mascot-trigger').click();
    const box=await page.locator('.mascot-panel').boundingBox(),viewport=page.viewportSize();
    assert.ok(box.x>=0&&box.y>=70&&box.x+box.width<=viewport.width&&box.y+box.height<=viewport.height);
    await page.screenshot({path:path.join(output,`mascot-panel-${mobile?'mobile':'desktop'}-${dark?'dark':'light'}.png`),fullPage:true});
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.mascot-trigger').evaluate(node=>node===document.activeElement),true);
  }
  assert.deepEqual(errors,[]);
});

test('all-target approval displays every fixed path and sends one approval',async t=>{
  const plan={start:[209,208,100],waypoints:[[40,170,100],[209,208,100]]};
  const batch={kind:'batch_wipe',start:[209,208,100],waypoints:[...plan.waypoints,[39,35,100],[209,208,100]],target_count:2};
  const data={...base('awaiting_confirmation'),phase:'wipe',task:{action:'wipe',selection:'all',color:'blue'},queue:cells.slice(0,2),plan,approved_batch_plan:batch,preview:{token:'batch'},current_target_id:'b1'};
  const {page,posts,send,errors}=await setup(t,data);
  await send('Clean all blue cells');
  await page.locator('#approve').waitFor();
  assert.match(await page.locator('#approvalHost').textContent(),/This approval covers all displayed paths/);
  await page.locator('#approvalHost .path-details summary').click();
  assert.equal(await page.locator('#approvalHost tbody tr').count(),4);
  await page.locator('#clearPath').check();
  await page.locator('#approve').click();
  await page.locator('#approve').waitFor({state:'detached',timeout:5000});
  assert.equal(posts.filter(p=>p.path.endsWith('/execute')).length,1);
  assert.deepEqual(errors,[]);
});
