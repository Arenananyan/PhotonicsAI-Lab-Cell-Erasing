'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const {t} = window.LabUI;
  LabUI.capture();LabUI.apply();
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let theme='light';
  try { theme=localStorage.getItem('labTheme')==='dark'?'dark':'light'; } catch {}
  function applyTheme(animate=false) {
    document.documentElement.dataset.theme=theme;
    document.documentElement.style.colorScheme=theme;
    const dark=theme==='dark',button=$('themeToggle');
    button.setAttribute('aria-pressed',String(dark));
    button.setAttribute('aria-label',t(dark?'Switch to light mode':'Switch to dark mode'));
    button.title=t(dark?'Switch to light mode':'Switch to dark mode');
    button.querySelector('use').setAttribute('href',dark?'#i-sun':'#i-theme');
    if(animate&&!reducedMotion.matches){
      document.body.classList.remove('theme-switching');
      void document.body.offsetWidth;
      document.body.classList.add('theme-switching');
      window.setTimeout(()=>document.body.classList.remove('theme-switching'),850);
    }
  }
  applyTheme();
  $('themeToggle').onclick=()=>{
    theme=theme==='dark'?'light':'dark';
    try { localStorage.setItem('labTheme',theme); } catch {}
    applyTheme(true);
  };
  const rawHome = document.body.dataset.home.split(',').map(Number);
  const home = rawHome.length === 3 && rawHome.every(Number.isFinite) ? rawHome : [209,208,100];
  const storageKey = 'lab.command.history.v1';
  const terminal = new Set(['completed','failed','cancelled','observed','rejected','stopped']);
  const working = new Set(['preparing','scanning','executing','positioning','answering']);
  let history = readStorage(storageKey, []);
  if (!Array.isArray(history)) history = [];
  history = history.filter(item => item && typeof item.id === 'string' && typeof item.prompt === 'string').slice(0,60);
  history = history.map(item=>Array.isArray(item.turns)?item:{id:item.id,prompt:item.prompt,updated:item.updated,turns:[item]});
  let chat = null, current = null, run = null, config = null, busy = false, emergencyBusy = false, generation = 0, timer;
  let traceState = '', traceIdentity = '', lastFocus, zoom = 1, panX = 0, panY = 0;
  let deleteTarget = null, deleteFocus = null;
  const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const label = value => t(String(value || '')).replaceAll('_',' ');
  const fmt = value => Number.isFinite(Number(value)) && value !== null && value !== '' ? Number(value).toFixed(2).replace(/\.00$/,'') : '—';
  function readStorage(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } }
  function saveHistory() { try { localStorage.setItem(storageKey,JSON.stringify(history.slice(0,60))); } catch { /* Session works without persistent storage. */ } }
  function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
  function remember(item) { history = [item,...history.filter(entry=>entry.id!==item.id)].slice(0,60); saveHistory(); renderHistory(); }
  function renderHistory() {
    $('history').replaceChildren();
    for (const item of history) {
      const row=document.createElement('div');row.className='history-row';
      const button = document.createElement('button'); button.className = 'history-item' + (chat?.id===item.id?' active':'');
      button.innerHTML = icon('chat')+'<span></span>';button.querySelector('span').textContent=item.prompt;
      button.title=item.prompt;button.setAttribute('aria-current',String(chat?.id===item.id));
      button.onclick=()=>selectHistory(item);
      const remove=document.createElement('button');remove.type='button';remove.className='delete-chat';
      remove.innerHTML=icon('trash');remove.title=t('Delete chat');remove.setAttribute('aria-label',t('Delete chat')+': '+item.prompt);
      remove.onclick=()=>{
        if(busy||activeRun())return;
        deleteTarget=item.id;deleteFocus=remove;$('deleteChatName').textContent=item.prompt;$('deleteChatDialog').showModal();
      };
      row.append(button,remove);$('history').append(row);
    }
    $('historyEmpty').hidden=history.length>0;
  }
  function setDrawer(open) {
    $('sidebar').classList.toggle('is-open',open);$('drawerBackdrop').hidden=!open;$('openSidebar').setAttribute('aria-expanded',String(open));
    $('sidebar').inert=!open && window.innerWidth<=800;
    if(window.innerWidth<=800) { document.body.style.overflow=open?'hidden':'';document.querySelector('.workspace').inert=open; }
    if(open) $('newCommand').focus(); else if(window.innerWidth<=800) $('openSidebar').focus();
  }
  $('openSidebar').onclick=()=>setDrawer(true);$('closeSidebar').onclick=()=>setDrawer(false);$('drawerBackdrop').onclick=()=>setDrawer(false);
  window.addEventListener('resize',()=>{if(window.innerWidth>800){setDrawer(false);$('sidebar').inert=false;document.querySelector('.workspace').inert=false;document.body.style.overflow='';}else $('sidebar').inert=!$('sidebar').classList.contains('is-open');});
  if(window.innerWidth<=800) $('sidebar').inert=true;
  const activeRun=()=>Boolean(run&&!terminal.has(run.state));
  function newCommand(){if(busy)return;if(activeRun()){notice(t('Finish or cancel the current command before opening another.'));return;}generation++;clearTimeout(timer);chat=null;current=null;run=null;traceState='';traceIdentity='';$('emptyState').hidden=false;$('conversation').hidden=true;$('turns').replaceChildren();$('prompt').value='';try{localStorage.removeItem('labRunId');localStorage.removeItem('labChatId');}catch{}notice();renderHistory();updateComposer();if(window.innerWidth<=800)setDrawer(false);$('prompt').focus();}
  $('newCommand').onclick=newCommand;
  $('cancelDeleteChat').onclick=()=>$('deleteChatDialog').close();
  $('deleteChatDialog').addEventListener('close',()=>{deleteTarget=null;if(deleteFocus?.isConnected)deleteFocus.focus();else $('newCommand').focus();});
  $('confirmDeleteChat').onclick=()=>{
    if(busy||activeRun()||!deleteTarget)return;
    const id=deleteTarget,remaining=history.filter(item=>item.id!==id);
    try{localStorage.setItem(storageKey,JSON.stringify(remaining));}
    catch{notice(t('Could not delete saved chat. Please try again.'));return;}
    history=remaining;
    if(chat?.id===id)newCommand();else {renderHistory();updateComposer();}
    $('deleteChatDialog').close();
  };
  document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();newCommand();}if(event.key==='Escape'&&$('sidebar').classList.contains('is-open'))setDrawer(false);});
  $('sidebar').addEventListener('keydown',event=>{
    if(event.key!=='Tab'||!$('sidebar').classList.contains('is-open'))return;
    const items=[...$('sidebar').querySelectorAll('a,button:not(:disabled)')].filter(item=>item.getClientRects().length);
    const first=items[0],last=items.at(-1);
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  });
  document.querySelectorAll('[data-prompt]').forEach(button=>button.onclick=()=>{$('prompt').value=button.dataset.prompt;resizeInput();$('prompt').focus();});
  function resizeInput(){$('prompt').style.height='auto';$('prompt').style.height=Math.min($('prompt').scrollHeight,140)+'px';}
  $('prompt').addEventListener('input',resizeInput);
  $('prompt').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('composer').requestSubmit();}});
  function updateComposer(){
    const mascot=document.querySelector('photonics-mascot');
    if(mascot)mascot.processing=busy||working.has(run?.state);
    const blocked=busy || !config || (run&&!terminal.has(run.state)&&run.state!=='awaiting_answer');
    mascot?.setAssistantState({blocked:Boolean(blocked),busy,reply:run?.state==='awaiting_answer',demo:config?.demo,draft:$('prompt').value});
    $('send').disabled=Boolean(blocked);$('prompt').disabled=busy;
    $('newCommand').disabled=busy||activeRun();
    $('history').querySelectorAll('button').forEach(button=>button.disabled=busy||activeRun());
    $('prompt').placeholder=run?.state==='awaiting_answer'?t('Reply to your lab…'):t('Ask your lab to do something…');
    $('composerHint').textContent=run?.state==='awaiting_answer'?t('Your answer continues this command'):run&&!terminal.has(run.state)?t('Following your current command'):t('Describe. Discover. Do.');
    resizeInput();
  }
  document.addEventListener('mascot-open',()=>updateComposer());
  document.addEventListener('mascot-draft',event=>{
    if(busy)return;
    $('prompt').value=event.detail.text;resizeInput();
  });
  document.addEventListener('mascot-request',event=>{
    if(busy||$('send').disabled)return;
    $('prompt').value=event.detail.text;resizeInput();
    event.preventDefault();$('composer').requestSubmit();
  });
  async function api(path,data){
    const response=await fetch(path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json','X-Lab-Control':'local'},body:data===undefined?undefined:JSON.stringify(data),signal:AbortSignal.timeout(15000)});
    let result;try{result=await response.json();}catch{throw Error('The lab service returned an unreadable response.');}
    if(!response.ok)throw Error(result.error||`Request failed (${response.status}).`);return result;
  }
  function buildConversation(){
    $('emptyState').hidden=true;$('conversation').hidden=false;traceState='';traceIdentity='';
    const turns=$('turns');turns.replaceChildren();
    for(const record of chat?.turns||[current]) {
      if(record===current)break;
      appendTurn(record);
      renderRun({...record.report,run_id:record.id,state:record.report?.state||'stopped',events:record.report?.events||[],audit:[],results:record.report?.results||[]},true);
      const article=turns.lastElementChild;article.classList.add('past-turn');
      for(const node of article.querySelectorAll('[id]')){node.dataset.pastId=node.id;node.removeAttribute('id');}
      article.querySelectorAll('.clearance input,.actions button,.turn-actions button').forEach(button=>button.disabled=true);
    }
    appendTurn(current);
  }
  function appendTurn(record){
    traceState='';traceIdentity='';const turns=$('turns');
    for(const message of [{role:'user',text:record.prompt},...(record.messages||[])]){
      const element=document.createElement('div');element.className=message.role==='user'?'user-message':'assistant-message';element.textContent=message.text;turns.append(element);
    }
    const assistant=document.createElement('article');assistant.className='assistant-turn';assistant.innerHTML=`<span class="assistant-avatar">${icon('optic')}</span><p class="assistant-name">Lab Agents</p><details id="reasoning" class="reasoning"><summary><svg class="optical-spinner" aria-hidden="true"><use href="#i-optic"/></svg><span class="reason-label">${t('Activity trace')}</span><svg class="chevron" aria-hidden="true"><use href="#i-chevron"/></svg></summary><div class="trace-wrap"><div class="trace" id="trace" aria-label="Recorded agent and tool activity"></div></div></details><div id="assistantMessage" class="assistant-message" role="status" aria-live="polite"></div><div id="questionHost"></div><div id="conditionHost"></div><div id="boardHost"></div><div id="visionHost"></div><div id="queueHost"></div><div id="insightsHost"></div><div id="executionHost"></div><div id="approvalHost"></div><div id="evidenceHost"></div><div id="runActions" class="turn-actions"></div>`;
    assistant.dataset.runId=record.id;
    turns.append(assistant);const details=$('reasoning');details.querySelector('summary').onclick=event=>{event.preventDefault();toggleReasoning(!details.open,details);};
  }
  function toggleReasoning(open,details=$('reasoning')){
    if(!details)return;
    details.getAnimations().forEach(animation=>animation.cancel());
    if(open===details.open)return;
    const start=details.getBoundingClientRect().height, collapsed=details.querySelector('summary').getBoundingClientRect().height+13;
    if(open)details.open=true;
    const end=open?details.getBoundingClientRect().height:collapsed;
    if(reducedMotion.matches || document.hidden){details.open=open;return;}
    details.style.overflow='hidden';const animation=details.animate([{height:start+'px'},{height:end+'px'}],{duration:350,easing:'cubic-bezier(.22,1,.36,1)'});
    animation.onfinish=()=>{details.open=open;details.style.overflow='';};
    animation.oncancel=()=>{details.style.overflow='';};
  }
  function traceLines(data){
    const lines=[{time:'',role:'reference',message:`HOME · X ${home[0]} / Y ${home[1]} / Z ${home[2]} mm`}];
    const events=(data.events||[]).map(event=>({time:event.time||'',role:event.agent||'agent',message:event.message||''}));
    const audits=(data.audit||[]).filter(entry=>['tool_request','tool_result','tool_error','llm_proposal'].includes(entry.kind)).map(entry=>{
      let message='';
      if(entry.kind==='tool_request')message=`${entry.server||'tool'}.${entry.name} requested`;
      if(entry.kind==='tool_result')message=`${entry.name} returned${entry.result?.data?.position_mm?' · position '+JSON.stringify(entry.result.data.position_mm):''}`;
      if(entry.kind==='tool_error')message=`${entry.name}: ${entry.error}`;
      if(entry.kind==='llm_proposal')message=`Groq ${entry.role||'planner'} · ${entry.result?.message||entry.result?.action||'proposal received'}`;
      return {time:entry.time||'',role:entry.kind==='llm_proposal'?'planner':'tool',message};
    });
    lines.push(...[...events,...audits].sort((a,b)=>a.time.localeCompare(b.time)));
    const coords=data.target?.printer_coordinates_mm;
    if(coords)lines.push({time:'',role:'vision',message:`Target · X ${fmt(coords.x)} / Y ${fmt(coords.y)}${coords.z!=null?' / Z '+fmt(coords.z):''} mm`});
    return lines;
  }
  function renderTrace(data){
    const active=working.has(data.state), details=$('reasoning');details.classList.toggle('active',active);
    details.querySelector('.reason-label').textContent=active?(data.state==='executing'?t('Executing the approved path…'):t('Preparing the request…')):`${t('Activity trace')} · ${label(data.state)}`;
    const identity=data.run_id;
    if(traceIdentity!==identity){traceIdentity=identity;$('trace').replaceChildren();}
    const lines=traceLines(data),host=$('trace');host.querySelector('.trace-cursor')?.remove();
    lines.forEach((line,index)=>{
      let node=host.children[index];const value=JSON.stringify(line);
      if(node?.dataset.value===value)return;
      if(!node){node=document.createElement('div');node.className='log-line';host.append(node);}
      node.dataset.value=value;node.innerHTML=`<span class="log-time">${esc(line.time?new Date(line.time).toLocaleTimeString([], {hour12:false}):'·')}</span><span class="log-role">${esc(line.role)}</span> ${esc(line.message)}`;
    });
    while(host.children.length>lines.length)host.lastChild.remove();
    if(active){const cursor=document.createElement('span');cursor.className='trace-cursor';cursor.textContent='█';cursor.setAttribute('aria-hidden','true');host.append(cursor);}
    if(traceState!==data.state){toggleReasoning(active);traceState=data.state;}
  }
  function keyed(id,key,html,setup){const host=$(id);if(host.dataset.key===key)return;host.dataset.key=key;host.innerHTML=html;LabUI.translate(host);setup?.(host);}
  function currentMessage(data){
    if(data.error)return data.error;
    if(data.state==='awaiting_answer')return t('A little more information will help me continue.');
    if(data.answer_message)return data.answer_message;
    if(data.state==='completed')return (data.summary|| (LabUI.language==='hy'?'Առաջադրանքն ավարտված է։':'The command is complete.'))+(data.simulated?(LabUI.language==='hy'?' Պրինտերի շարժումը սիմուլյացիոն է։':' Printer motion was simulated.'):'')+(data.synthetic_target?(LabUI.language==='hy'?' Թիրախն ու արդյունքի պատկերները սինթետիկ են։':' The target and evidence are synthetic.'):'');
    if(data.state==='awaiting_confirmation')return data.task?.message||t('The path is ready. Review the target and complete route below before approving.');
    if(data.state==='executing')return data.stop_requested?t('Stop requested. The current queued path may finish; no next path will begin.'):t('Following the approved path. I’ll report the result when the tools return.');
    if(data.state==='preparing'||data.state==='scanning')return data.task?.message||t('I’m checking your request.');
    if(data.state==='failed')return t('The command could not finish. No automatic movement retry was made.');
    if(data.state==='cancelled')return t('This command was cancelled.');
    if(data.state==='stopped')return t('The task has stopped.');
    return data.task?.message||label(data.state);
  }
  function renderRun(data,historical=false){
    const main=$('main'),follow=main.scrollHeight-main.scrollTop-main.clientHeight<90;
    if(!historical){run=data;current.state=data.state;}
    if(!historical&&terminal.has(data.state)&&!data.archived) {
      const report={};
      for(const key of ['run_id','state','prompt','task','limits','phase','queue','current_target_id','results','answer_message','answer_warning','summary','approved_batch_plan','verification','ranked_cells','suggestions','suggestion_reason','condition_result','error','simulated','synthetic_target','plan','target','events','observation_images','observation_image_warning','distances','selected_targets','question_context']) if(data[key]!==undefined)report[key]=data[key];
      current.report=report;
    }
    if(!historical)saveHistory();renderTrace(data);$('assistantMessage').textContent=currentMessage(data);
    keyed('questionHost',data.state+':'+data.question,data.state==='awaiting_answer'?`<div class="question" data-content>${esc(data.question)}</div>`:'');
    renderCondition(data);renderBoard(data);renderVision(data);renderQueue(data);renderInsights(data);renderExecution(data);renderApproval(data,historical);renderEvidence(data);
    if(historical)keyed('runActions','historical','');else {renderActions(data);updateComposer();}
    const position=data.verification?.position_mm;
    if(position){const node=document.createElement('p');node.className='scope';node.textContent=`XYZ · ${'xyz'.split('').map(axis=>`${axis.toUpperCase()} ${fmt(position[axis])}`).join(' / ')} mm`;$('assistantMessage').append(node);}
    if(data.answer_warning){const warning=document.createElement('p');warning.className='fine-print';warning.textContent=data.answer_warning;$('assistantMessage').append(warning);}
    if(!historical&&follow)requestAnimationFrame(()=>main.scrollTop=main.scrollHeight);
  }
  function renderCondition(data) {
    const result=data.condition_result, condition=data.task?.condition||result?.condition;
    const key=JSON.stringify([LabUI.language,condition,result]);
    if(!condition){keyed('conditionHost',key,'');return;}
    const operator={gt:'>',gte:'≥',eq:'=',lt:'<',lte:'≤'}[condition.operator]||'?';
    const rhs=condition.compare_metric?t(condition.compare_metric):fmt(condition.value);
    keyed('conditionHost',key,`<div class="condition-result ${result&&!result.passed?'unmet':''}"><strong>${t(result?(result.passed?t('Condition met'):t('Condition not met')):'Condition')}</strong><div>${esc(t(condition.metric))} ${operator} ${esc(rhs)}${result?` · ${fmt(result.left)} ${operator} ${fmt(result.right)}`:''}</div></div>`);
  }
  function renderQueue(data) {
    const queue=data.queue||[],results=data.results||[];
    keyed('queueHost',JSON.stringify([LabUI.language,queue,results,data.current_target_id]),queue.length?`<section class="card"><div class="card-heading"><span>${icon('scan')}${t('Target queue')}</span><small>${results.length} / ${queue.length}</small></div><div class="insight-content"><ol class="queue-list">${queue.map((cell,index)=>{
      const verdict=results.find(result=>result.target_id===cell.target_id)?.verdict;
      const state=verdict?label(verdict):cell.target_id===data.current_target_id?t('Current'):t('Pending');
      const xy=cell.printer_coordinates_mm||{};
      return `<li class="${!verdict&&cell.target_id===data.current_target_id?'current':''}"><span>${index+1}. ${esc(label(cell.color))}</span><span>${fmt(cell.area_mm2)} mm² · X ${fmt(xy.x)} / Y ${fmt(xy.y)}</span><span class="badge">${esc(state)}</span></li>`;
    }).join('')}</ol></div></section>`:'');
  }
  function renderInsights(data) {
    const ranked=data.ranked_cells||[],suggestions=data.suggestions||[];
    const visible=data.state==='observed'||(data.state==='awaiting_answer'&&data.question_context==='size_choice');
    const key=JSON.stringify([LabUI.language,visible,ranked,suggestions,data.suggestion_reason,data.distances,data.selected_targets]);
    const groups=['blue','green'].map(color=>{
      const cells=ranked.filter(cell=>cell.color===color);
      return cells.length?`<div class="ranked-group"><h3>${esc(label(color))} · ${cells.length}</h3><ol>${cells.map((cell,rank)=>`<li class="ranked-cell ${Number.isInteger(cell.image_index)?'with-image':'without-image'}"><span class="cell-rank">${rank+1}.</span>${Number.isInteger(cell.image_index)?`<button type="button" class="cell-image" data-cell-image="${cell.image_index}" aria-label="${esc(t('Cell'))} #${cell.display_number}"><img loading="lazy" src="${observationUrl(data,'cells/'+cell.image_index)}" alt="${esc(t('Cell'))} #${cell.display_number}"><span class="cell-number">#${cell.display_number}</span></button>`:''}<span class="cell-measurements">${fmt(cell.area_mm2)} mm²<br>X=${fmt(cell.printer_coordinates_mm.x)}, Y=${fmt(cell.printer_coordinates_mm.y)} mm</span></li>`).join('')}</ol></div>`:'';
    }).join('');
    keyed('insightsHost',key,visible?`${(data.selected_targets||[]).map(c=>`<section class="card"><div class="insight-content"><strong>${LabUI.language==='hy'?'Ընտրված բջիջ':'Selected cell'} · ${esc(label(c.color))}</strong><p>${fmt(c.area_mm2)} mm² · X=${fmt(c.printer_coordinates_mm.x)}, Y=${fmt(c.printer_coordinates_mm.y)} mm</p></div></section>`).join('')}${(data.distances||[]).map(d=>`<section class="card"><div class="insight-content"><strong>XY · ${fmt(d.distance_mm)} mm</strong><p>(${d.from_xy_mm.map(fmt).join(', ')}) → (${d.to_xy_mm.map(fmt).join(', ')})</p><p class="fine-print">${LabUI.language==='hy'?'Կենտրոնից կենտրոն՝ տախտակի հարթության վրա։':'Center-to-center on the board plane.'}</p></div></section>`).join('')}${ranked.length?`<section class="card"><div class="card-heading"><span>${icon('scan')}${t('Cells by measured area')}</span></div><div class="insight-content">${groups}</div></section>`:''}${suggestions.length?`<section class="card"><div class="card-heading"><span>${icon('optic')}${t('Agent suggestions')}</span></div><div class="insight-content"><p data-content>${esc(data.suggestion_reason||'')}</p><div class="suggestion-list">${suggestions.map((item,index)=>`<button type="button" class="button secondary" data-suggestion="${index}">${esc(item.label)}</button>`).join('')}</div><p class="fine-print">${t('Selecting a suggestion only fills the command. Review the plan and approve movement separately.')}</p></div></section>`:''}`:'',host=>{
      host.querySelectorAll('[data-cell-image]').forEach(button=>{
        const image=button.querySelector('img');
        button.onclick=()=>openImage(image.src,image.alt);
        image.onerror=()=>{image.hidden=true;button.disabled=true;button.title=t('Cell image unavailable');button.classList.add('unavailable');};
      });
      host.querySelectorAll('[data-suggestion]').forEach(button=>button.onclick=()=>{
        if(busy||activeRun()){notice(t('Finish or cancel the current command before opening another.'));return;}
        $('prompt').value=suggestions[Number(button.dataset.suggestion)].prompt;resizeInput();$('prompt').focus();
        $('composer').scrollIntoView({behavior:reducedMotion.matches?'instant':'smooth',block:'end'});
      });
    });
  }
  function observationUrl(data,part){return `/api/runs/${encodeURIComponent(data.run_id)}/observation/${part}`;}
  function renderBoard(data){
    const gallery=data.observation_images;
    if(!gallery?.board_image){keyed('boardHost',data.observation_image_warning||'hidden',data.observation_image_warning?`<p class="fine-print">${t('Board image unavailable')} · ${esc(data.observation_image_warning)}</p>`:'');return;}
    const key=data.run_id+':'+gallery.frame_id;
    keyed('boardHost',key,`<section class="card board-observation"><div class="card-heading"><span>${icon('eye')}${t('Board observation')}</span><small>${t('CAPTURED FRAME')}</small></div><div class="image-stage"><p class="scan-label">${t('Loading captured image…')}</p><img class="cv-image" alt="${t('Board observation')}" tabindex="0" role="button" aria-label="${t('Board observation')}"></div><div class="insight-content"><p class="fine-print">${t('Numbers match the board image. Cell pictures use the same captured frame.')}</p><span class="endpoint-note">${esc(gallery.acquired_at?new Date(gallery.acquired_at).toLocaleString():'')} · ${esc(gallery.frame_id)}</span></div></section>`,host=>{
      const image=host.querySelector('img');image.onload=()=>image.parentElement.classList.add('loaded');
      image.onerror=()=>{image.hidden=true;host.querySelector('.scan-label').textContent=t('Board image unavailable');};
      image.src=observationUrl(data,'board');image.onclick=()=>openImage(image.src,image.alt);
      image.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openImage(image.src,image.alt);}};
    });
  }
  function imageUrl(data){return `/api/runs/${encodeURIComponent(data.run_id)}/image?t=${encodeURIComponent(data.target?.frame_id||data.run_id)}`;}
  function renderVision(data){
    const target=data.target,visible=!!target?.annotated_image;
    const key=visible?data.run_id+':'+(target?.frame_id||'scanning'):'hidden';
    if(!visible){keyed('visionHost',key,'');return;}
    const coords=target?.printer_coordinates_mm;
    const badges=target?`<span class="badge green">${esc(label(target.color||target.label||'Target'))}</span>${target.confidence!=null?`<span class="badge">${fmt(Number(target.confidence)*100)}% confidence</span>`:''}${coords?Object.entries(coords).map(([axis,value])=>`<span class="badge">${esc(axis.toUpperCase())} ${fmt(value)} mm</span>`).join(''):''}${target.area_mm2!=null?`<span class="badge">${fmt(target.area_mm2)} mm²</span>`:''}`:'';
    keyed('visionHost',key,`<section class="card"><div class="card-heading"><span>${icon('scan')} ${target?t('Target acquired'):t('Computer vision')}</span><small>${t('ANNOTATED FRAME')}</small></div><div class="image-stage"><div class="scan-label"><strong>Locating your target</strong>Mapping the field of view…</div><span class="scanline"></span><span class="bracket"></span>${target?.annotated_image?'<img class="cv-image" alt="Annotated detected target" tabindex="0" role="button" aria-label="Enlarge annotated target image">':''}</div>${badges?`<div class="metadata">${badges}</div>`:''}</section>`,host=>{
      const image=host.querySelector('img');if(!image)return;
      image.onload=()=>image.parentElement.classList.add('loaded');image.onerror=()=>{host.querySelector('.scan-label').textContent=t('Target image unavailable');host.querySelector('.scanline').hidden=true;host.querySelector('.bracket').hidden=true;};
      image.src=imageUrl(data);image.onclick=()=>openImage(image.src,image.alt);image.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openImage(image.src,image.alt);}};
    });
  }
  function renderApproval(data,historical=false){
    const plan=data.approved_batch_plan||data.plan,awaiting=!historical&&data.state==='awaiting_confirmation';
    if(!plan){keyed('approvalHost','hidden','');return;}
    const key=JSON.stringify([data.run_id,data.state,data.authorization?.id,data.preview?.token,plan,data.task,data.limits]);
    const task=data.task||{},points=plan.waypoints||[],speed=data.limits?.speed_mm_s;
    const title=['home','observe_home'].includes(data.phase)?t('Review the home path'):task.action==='wipe'?t('Review the cleaning path'):t('Review the movement path');
    const destination=plan.destination||points.at(-1)||[];
    const relation=(data.distances||[]).find(d=>d.to_target_id===data.current_target_id);
    const relationText=relation?`<p>${LabUI.language==='hy'?'Հենակետից ընտրված թիրախ՝':'Reference to selected target:'} (${relation.from_xy_mm.map(fmt).join(', ')}) → (${relation.to_xy_mm.map(fmt).join(', ')}) · <strong>${fmt(relation.distance_mm)} mm</strong> · XY</p>`:'';
    const scope=task.action==='wipe'?`${label(task.selection)} · ${label(task.color)} · ${task.selection==='all'?(LabUI.language==='hy'?'մինչև 20 սկզբնական թիրախ':'up to 20 initial targets'):(LabUI.language==='hy'?'մեկ թիրախ':'one target')} · ${LabUI.language==='hy'?'մեկական շրջան':'one pass each'}. Z=14.5 mm · R=10 mm.`:`Destination: ${Array.isArray(destination)?destination.map(fmt).join(', '):JSON.stringify(destination)} mm.`;
    keyed('approvalHost',key,`<section class="card"><div class="card-heading"><span>${icon('check')}${awaiting?title:t('Displayed path')}</span><small>${awaiting?t('APPROVAL REQUIRED'):t('RECORDED PLAN')}</small></div><div class="approval-content"><p>${esc(scope)}</p>${plan.kind==='batch_wipe'?`<p>${LabUI.language==='hy'?'Այս հաստատումն ընդգրկում է ստորև ցուցադրված բոլոր ճանապարհները։ Մնացորդով բջիջները չեն կրկնվի․ արդյունքները կամփոփվեն վերջում։':'This approval covers all displayed paths. Residue will be reported at the end; cells will not be repeated.'} (${plan.target_count})</p>`:''}${relationText}<p class="scope">HOME (${home.join(', ')}) mm${speed!=null?' · '+esc(speed)+' mm/s (XY + Z)':''}</p><details class="path-details"><summary>${t("View complete path")} · ${points.length} ${t("waypoints")}</summary><div class="table-wrap"><table><thead><tr><th>Step</th><th>X mm</th><th>Y mm</th><th>Z mm</th></tr></thead><tbody>${points.map((point,index)=>`<tr><td>${index+1}</td>${point.map(value=>`<td>${esc(value)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${points.length?'':'<p class="fine-print">Already at the initial position; there is no travel step.</p>'}</details>${awaiting?`<p class="fine-print">Approve within 110 seconds of path preparation. The task limit is 30 minutes. Home is a configured position, not a G28 homing command.</p><label class="clearance"><input id="clearPath" type="checkbox"><span>I reviewed the complete path, motion limits, and clearance of the entire tool footprint${task.action==='wipe'?' including Z 14.5 mm and the R 10 mm circle':''}.</span></label><div class="actions"><button id="approve" class="button" disabled>${t('Approve & execute')}</button><button id="cancelRun" class="button secondary">Cancel command</button></div>`:'<p class="fine-print">Only the displayed path is covered by its approval. A new path requires a new confirmation.</p>'}</div></section>`,()=>{
      if(!awaiting)return;$('clearPath').onchange=()=>{$('approve').disabled=busy||!$('clearPath').checked;};
      $('approve').onclick=()=>{if(busy||!$('clearPath').checked||run?.state!=='awaiting_confirmation')return;control('execute',{confirmed:true,clear_path:true});};
      $('cancelRun').onclick=()=>control('cancel',{});
    });
    if($('approve'))$('approve').disabled=busy||!$('clearPath').checked;
  }
  function executionStage(data){
    const audits=data.audit||[];let lastExec=-1,lastScan=-1;
    audits.forEach((entry,index)=>{if(entry.name==='execute_sequence')lastExec=index;if(entry.name==='scanner_scan_current_frame')lastScan=index;});
    if(lastExec>=0&&lastScan>lastExec)return 3;
    if(lastExec>=0)return 2;
    if(lastScan>=0)return 1;
    return 0;
  }
  function renderExecution(data){
    if(!['executing','positioning'].includes(data.state)){keyed('executionHost','hidden','');return;}
    const points=[data.plan?.start||home,...(data.plan?.waypoints||[])];
    const target=data.target?.printer_coordinates_mm||{x:points.at(-1)?.[0]??home[0],y:points.at(-1)?.[1]??home[1]};
    const all=[...points,home,[target.x,target.y]],xs=all.map(p=>Number(p[0])).filter(Number.isFinite),ys=all.map(p=>Number(p[1])).filter(Number.isFinite);
    const minX=Math.min(...xs)-25,maxX=Math.max(...xs)+25,minY=Math.min(...ys)-25,maxY=Math.max(...ys)+25;
    const project=p=>[40+(Number(p[0])-minX)/(maxX-minX)*320,180-(Number(p[1])-minY)/(maxY-minY)*145];
    const path=points.map((p,i)=>(i?'L':'M')+project(p).join(',')).join(' '), hp=project(home),tp=project([target.x,target.y]);
    const stage=executionStage(data),key=JSON.stringify([data.run_id,data.phase,points,stage,reducedMotion.matches]);
    keyed('executionHost',key,`<section class="card execution"><div class="photon-bar"></div><div class="card-heading"><span>${icon('optic')} Toolhead execution</span><small>PLAN VISUALIZATION</small></div><div class="hardware-steps">${[t('Home / path check'),t('Before capture'),t('Toolhead action'),t('After capture')].map((title,i)=>`<div class="hardware-step ${i===stage?'current':i<stage?'done':''}"><span class="step-dot">${i<stage?'✓':i+1}</span>${title}</div>`).join('')}</div><div class="radar-wrap"><svg class="radar" viewBox="0 0 400 210" role="img" aria-label="Illustration of the approved path. Not live position telemetry."><defs><pattern id="bedGrid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" stroke="#dfe7da" stroke-width=".6"/></pattern></defs><rect x="20" y="20" width="360" height="175" rx="5" fill="url(#bedGrid)" stroke="#e0e6dd"/><path class="radar-path" d="${path}"/><circle cx="${hp[0]}" cy="${hp[1]}" r="4" fill="#1e4d2b"/><text x="${hp[0]+9}" y="${hp[1]-9}">HOME</text><circle cx="${tp[0]}" cy="${tp[1]}" r="8" stroke="#68b848" fill="#68b84815"/><text x="${tp[0]+11}" y="${tp[1]+18}">TARGET</text><g ${reducedMotion.matches||points.length<2||stage!==2?`transform="translate(${hp.join(',')})"`:""}><circle class="radar-ring" r="5"/><circle class="radar-node" r="4"/>${!reducedMotion.matches&&points.length>1&&stage===2?`<animateMotion dur="7s" repeatCount="indefinite" path="${path}"/>`:''}</g></svg><div class="radar-note"><span class="target-pulse">X ${fmt(target.x)} · Y ${fmt(target.y)} mm</span><span>Schematic · no live telemetry</span></div></div></section>`);
  }
  function renderEvidence(data){
    const records=data.results||[];const key=JSON.stringify([data.run_id,records]);
    keyed('evidenceHost',key,records.map((record,index)=>{
      const images=record.evidence?.images?.length===2;
      const url=side=>`/api/runs/${encodeURIComponent(data.run_id)}/evidence/${index}/${side}`;
      return `<section class="card"><div class="card-heading"><span>${icon('eye')} ${esc(label(record.verdict)||t('Visual assessment'))}</span><small>${'TARGET '+(index+1)}</small></div>${images?`<div class="comparison"><img src="${esc(url('after'))}" alt="After action evidence"><img class="before-layer" src="${esc(url('before'))}" alt="Before action evidence"><span class="compare-label before">BEFORE</span><span class="compare-label after">AFTER</span><span class="compare-divider"></span><input type="range" min="0" max="100" value="50" aria-label="Before and after image comparison" aria-valuetext="50 percent before image"></div><div class="comparison-footer"><span>Drag to compare</span><button class="text-button evidence-zoom" data-src="${esc(url('before'))}">Enlarge before</button><button class="text-button evidence-zoom" data-src="${esc(url('after'))}">Enlarge after</button></div>`:''}<div class="evidence-content"><span data-content>${esc(record.assessment?.message||'')}</span>${record.evidence?.remaining_fraction!=null?`<div class="metadata"><span class="badge">Colored residue ${fmt(100*record.evidence.remaining_fraction)}%</span></div>`:''}</div></section>`;
    }).join(''),host=>{
      host.querySelectorAll('.evidence-zoom').forEach(button=>button.onclick=()=>openImage(button.dataset.src,'Inspection evidence'));
      host.querySelectorAll('.comparison').forEach(card=>{
        const input=card.querySelector('input');let animation,interacted=false;
        const position=value=>{card.style.setProperty('--split',value+'%');input.value=value;input.setAttribute('aria-valuetext',Math.round(value)+' percent before image');};
        input.oninput=()=>{interacted=true;cancelAnimationFrame(animation);position(input.value);};
        input.onpointerdown=()=>{interacted=true;cancelAnimationFrame(animation);};input.onkeydown=()=>{interacted=true;cancelAnimationFrame(animation);};
        const start=performance.now();function sweep(now){if(interacted||!card.isConnected)return;const t=Math.min((now-start)/1400,1);position(50+27*Math.sin(t*Math.PI*2)*Math.sin(t*Math.PI));if(t<1)animation=requestAnimationFrame(sweep);else position(50);}
        if(!reducedMotion.matches)animation=requestAnimationFrame(sweep);
        card.querySelectorAll('img').forEach(image=>image.onerror=()=>{card.querySelectorAll('img').forEach(img=>img.hidden=true);input.disabled=true;const error=document.createElement('p');error.textContent=t('Evidence image unavailable');card.append(error);});
      });
    });
  }
  function renderActions(data){
    const active=!terminal.has(data.state),question=data.state==='awaiting_answer';
    keyed('runActions',data.state+':'+data.stop_requested+':'+config?.printer_mode,`${active?'<button id="stopTask" class="button secondary">Stop after current path</button>':''}${question?'<button id="cancelQuestion" class="button secondary">Cancel command</button>':''}${!active&&config?.printer_mode==='mock'?'<button id="resetSimulation" class="text-button">Reset simulation</button>':''}`,()=>{
      if($('stopTask'))$('stopTask').onclick=()=>control('stop-task',{});
      if($('cancelQuestion'))$('cancelQuestion').onclick=()=>control('cancel',{});
      if($('resetSimulation'))$('resetSimulation').onclick=async()=>{if(busy)return;busy=true;updateComposer();try{await api('/api/simulation/reset',{});notice(t('Simulated printer reset.'));}catch(error){notice(error.message);}finally{busy=false;if(run)renderRun(run);else updateComposer();}};
    });
    $('runActions').querySelectorAll('button').forEach(button=>button.disabled=busy||(button.id==='stopTask'&&data.stop_requested===true));
  }
  async function poll(expectedGeneration=generation){
    if(!current||expectedGeneration!==generation)return;
    const id=current.id;
    try{const result=await api('/api/runs/'+encodeURIComponent(id));if(expectedGeneration!==generation||current?.id!==id)return;renderRun(result);notice();if(!terminal.has(result.state))timer=setTimeout(()=>poll(expectedGeneration),1000);}
    catch(error){if(expectedGeneration!==generation)return;notice(error.message==='Unknown run'?t('This run is no longer available on the server. Its saved conversation is shown; start a new command to continue.'):error.message);if(error.message==='Unknown run'){
      try{localStorage.removeItem('labRunId');}catch{}
      renderRun({...current.report,run_id:id,state:current.report?.state||'stopped',events:[],audit:[],results:current.report?.results||[],archived:true});
    }else timer=setTimeout(()=>poll(expectedGeneration),3000);}
  }
  async function selectHistory(item){if(busy)return;if(activeRun()){notice(t('Finish or cancel the current command before opening another.'));return;}generation++;clearTimeout(timer);chat=item;current=chat.turns.at(-1);run=null;buildConversation();renderHistory();notice();try{localStorage.setItem('labRunId',current.id);localStorage.setItem('labChatId',chat.id);}catch{}if(window.innerWidth<=800)setDrawer(false);updateComposer();await poll();$('main').scrollTop=$('main').scrollHeight;}
  async function control(action,payload){
    if(busy||!current)return;const id=current.id,version=++generation;clearTimeout(timer);busy=true;notice();renderRun(run);
    try{await api(`/api/runs/${encodeURIComponent(id)}/${action}`,payload);if(version===generation){clearTimeout(timer);await poll(version);}}
    catch(error){if(version===generation)notice(error.message);}finally{busy=false;if(run)renderRun(run);else updateComposer();}
  }
  $('composer').onsubmit=async event=>{
    event.preventDefault();const text=$('prompt').value.trim();if(!text||busy||$('send').disabled)return;
    busy=true;updateComposer();notice();const version=generation;
    try{
      if(run?.state==='awaiting_answer'){
        await api(`/api/runs/${encodeURIComponent(current.id)}/answer`,{answer:text});
        if(version!==generation)return;current.messages=[...(current.messages||[]),{role:'assistant',text:run.question},{role:'user',text}];saveHistory();buildConversation();
      }else{
        const chatId=chat?.id||crypto.randomUUID();
        const response=await api('/api/prepare',{prompt:text,chat_id:chatId,previous_run_ids:(chat?.turns||[]).slice(-8).map(turn=>turn.id)});if(version!==generation)return;
        current={id:response.run_id,prompt:text,messages:[],state:'preparing',updated:Date.now()};
        if(!chat)chat={id:chatId,prompt:text,turns:[],updated:Date.now()};
        chat.turns.push(current);chat.updated=Date.now();run=null;remember(chat);buildConversation();
        try{localStorage.setItem('labRunId',current.id);localStorage.setItem('labChatId',chat.id);}catch{}
      }
      $('prompt').value='';clearTimeout(timer);await poll(version);
      $('main').scrollTop=$('main').scrollHeight;
    }catch(error){if(version===generation)notice(error.message);}finally{busy=false;if(run)renderRun(run);else updateComposer();}
  };
  $('emergency').onclick=()=>{$('confirmDialog').showModal();};
  $('dismissConfirm').onclick=()=>$('confirmDialog').close();
  $('confirmEmergency').onclick=async()=>{if(emergencyBusy)return;emergencyBusy=true;$('confirmEmergency').disabled=true;try{await api('/api/stop',{confirmed:true});$('confirmDialog').close();notice(t('Emergency shutdown requested. Check the printer.'));if(current){clearTimeout(timer);await poll();}}catch(error){notice(error.message);$('confirmDialog').close();}finally{emergencyBusy=false;$('confirmEmergency').disabled=false;updateComposer();}};
  function applyZoom(){$('zoomImage').style.transform=`translate(${panX}px,${panY}px) scale(${zoom})`;}
  function setZoom(value){zoom=Math.min(6,Math.max(1,value));if(zoom===1)panX=panY=0;applyZoom();}
  function openImage(src,alt){lastFocus=document.activeElement;$('zoomImage').src=src;$('zoomImage').alt=alt;zoom=1;panX=panY=0;applyZoom();$('lightbox').showModal();}
  $('closeLightbox').onclick=()=>$('lightbox').close();$('lightbox').addEventListener('close',()=>lastFocus?.focus());
  $('zoomIn').onclick=()=>setZoom(zoom+.5);$('zoomOut').onclick=()=>setZoom(zoom-.5);$('zoomReset').onclick=()=>setZoom(1);
  $('imageViewport').addEventListener('wheel',event=>{event.preventDefault();setZoom(zoom-event.deltaY*.003);},{passive:false});
  const pointers=new Map();let lastDistance=0;
  $('imageViewport').addEventListener('pointerdown',event=>{pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});$('imageViewport').setPointerCapture(event.pointerId);if(pointers.size===2){const [a,b]=[...pointers.values()];lastDistance=Math.hypot(a.x-b.x,a.y-b.y);}});
  $('imageViewport').addEventListener('pointermove',event=>{
    if(!pointers.has(event.pointerId))return;const old=pointers.get(event.pointerId);pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
    if(pointers.size===2){const [a,b]=[...pointers.values()],distance=Math.hypot(a.x-b.x,a.y-b.y);if(lastDistance)setZoom(zoom*distance/lastDistance);lastDistance=distance;}else if(zoom>1){panX+=event.clientX-old.x;panY+=event.clientY-old.y;applyZoom();}
  });
  for(const type of ['pointerup','pointercancel','lostpointercapture'])$('imageViewport').addEventListener(type,event=>{pointers.delete(event.pointerId);lastDistance=0;});
  reducedMotion.addEventListener('change',()=>{if(run)renderExecution(run);});
  function renderConfig(){
    if(!config)return;
    $('modeText').textContent=t(config.demo?'Synthetic simulation':config.printer_mode==='mock'?'Simulated printer':config.motion_enabled?'Real printer · motion enabled':'Real printer · preview only');
    $('emergency').querySelector('span').textContent=t(config.printer_mode==='mock'?t('Stop simulation'):t('Emergency stop'));
  }
  $('language').onclick=()=>{
    LabUI.toggle();applyTheme();renderConfig();renderHistory();
    document.querySelector('photonics-mascot')?.updateLabels();
    if(run){buildConversation();renderRun(run);}
    updateComposer();
  };
  renderHistory();
  {
    api('/api/config').then(result=>{config=result;renderConfig();updateComposer();}).catch(error=>{notice('Lab service unavailable. '+error.message);$('modeText').textContent=t('Disconnected');$('mode').classList.add('disconnected');updateComposer();});
    let remembered,rememberedChat;try{remembered=localStorage.getItem('labRunId');rememberedChat=localStorage.getItem('labChatId');}catch{}
    if(remembered||rememberedChat){
      const item=history.find(entry=>entry.id===rememberedChat)||history.find(entry=>entry.turns.some(turn=>turn.id===remembered));
      if(item)selectHistory(item);
      else {
        busy=true;updateComposer();
        api('/api/runs/'+encodeURIComponent(remembered)).then(data=>{
          current={id:remembered,prompt:data.prompt||'Command',messages:[],state:data.state,updated:Date.now()};chat={id:remembered,prompt:current.prompt,turns:[current],updated:Date.now()};remember(chat);buildConversation();renderRun(data);try{localStorage.setItem('labChatId',chat.id);}catch{}if(!terminal.has(data.state))timer=setTimeout(()=>poll(),1000);
        }).catch(error=>{try{localStorage.removeItem('labRunId');}catch{}notice(error.message==='Unknown run'?t('This run is no longer available on the server. Its saved conversation is shown; start a new command to continue.'):error.message);}).finally(()=>{busy=false;if(run)renderRun(run);else updateComposer();});
      }
    }
    updateComposer();
  }
})();
