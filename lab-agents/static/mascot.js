'use strict';
(() => {
  // A dependency-free component: <photonics-mascot asset-base="/static/mascot/">.
  // Durations are from the supplied asset manifest, in milliseconds.
  const durations={wave:2850,hop:2790};
  let panelId=0;
  class PhotonicsMascot extends HTMLElement {
    connectedCallback(){
      this._processing=this._processing||false;
      this._paused=false;
      try{this._paused=localStorage.getItem('labMascotPaused')==='true';}catch{}
      this._motion=matchMedia('(prefers-reduced-motion: reduce)');
      this._cache=new Map();this._version=0;this._url=null;this._timer=null;this._state=null;
      this._lifecycle=new AbortController();
      const {signal}=this._lifecycle;
      this.innerHTML='<button type="button" class="mascot-trigger"><img class="mascot-image" width="256" height="256" alt="" aria-hidden="true" draggable="false"></button><button type="button" class="mascot-pause"><svg viewBox="0 0 16 16" aria-hidden="true"><path/></svg><span></span></button>';
      this._trigger=this.querySelector('.mascot-trigger');
      this._image=this.querySelector('img');this._pause=this.querySelector('.mascot-pause');
      this._createPanel(signal);
      this._trigger.addEventListener('pointerenter',event=>{if(event.pointerType!=='touch')this.play('wave');},{signal});
      this._trigger.addEventListener('focus',()=>this.play('wave'),{signal});
      this._trigger.addEventListener('click',()=>{
        this.play('hop');
        if(this._panel.matches(':popover-open'))this.closePanel(true);else this.openPanel();
      },{signal});
      this._pause.addEventListener('click',()=>{
        this._paused=!this._paused;
        try{localStorage.setItem('labMascotPaused',String(this._paused));}catch{}
        this._rest();this.updateLabels();
      },{signal});
      this._motion.addEventListener('change',()=>{this._rest();this.updateLabels();},{signal});
      document.addEventListener('visibilitychange',()=>this._rest(),{signal});
      this.updateLabels();this._rest();
    }
    disconnectedCallback(){
      clearTimeout(this._timer);this._timer=null;this._version++;
      this._lifecycle?.abort();
      this._panel?.remove();
      if(this._image){this._image.onload=null;this._image.onerror=null;this._image.removeAttribute('src');}
      if(this._url)URL.revokeObjectURL(this._url);
      this._url=null;this._cache?.clear();
    }
    set processing(value){
      value=Boolean(value);
      if(value===this._processing)return;
      this._processing=value;
      if(this._lifecycle&&!this._lifecycle.signal.aborted)this._rest();
    }
    get processing(){return Boolean(this._processing);}
    _createPanel(signal){
      const panel=document.createElement('section');
      panel.id='mascot-assistant-'+(++panelId);panel.className='mascot-panel';
      panel.setAttribute('popover','auto');panel.setAttribute('role','dialog');
      panel.innerHTML='<header><strong data-label="Photonics assistant"></strong><button type="button" class="icon-button mascot-close" data-name="Close assistant">×</button></header><p class="mascot-intro" data-label="Ask about your lab or describe a task. Results appear in the conversation."></p><p class="mascot-panel-status" role="status"></p><div class="mascot-shortcuts"><button type="button" data-command="Inspect the cells." data-label="Inspect cells"></button><button type="button" data-command="What is the printer status?" data-label="Printer status"></button><button type="button" data-command="Clean the largest blue cell." data-label="Clean largest blue"></button><button type="button" data-command="Return home." data-label="Return home"></button></div><form class="mascot-question-form"><label data-label="Question or task"></label><textarea rows="3" maxlength="2000" required></textarea><button type="submit" class="button" data-label="Send to lab"></button></form><p class="fine-print" data-label="Movement still requires your path approval."></p>';
      const input=panel.querySelector('textarea');input.id=panel.id+'-input';
      panel.querySelector('label').htmlFor=input.id;
      document.querySelector('.workspace').append(panel);
      this._panel=panel;this._question=input;
      this._trigger.setAttribute('aria-controls',panel.id);
      this._trigger.setAttribute('aria-haspopup','dialog');
      this._trigger.setAttribute('aria-expanded','false');
      panel.querySelector('.mascot-close').addEventListener('click',()=>this.closePanel(true),{signal});
      panel.addEventListener('toggle',event=>{
        const open=event.newState==='open';
        this.toggleAttribute('data-panel-open',open);this._trigger.setAttribute('aria-expanded',String(open));
      },{signal});
      panel.addEventListener('keydown',event=>{
        if(event.key==='Escape'){event.preventDefault();event.stopPropagation();this.closePanel(true);}
      },{signal});
      const draft=()=>this.dispatchEvent(new CustomEvent('mascot-draft',{bubbles:true,detail:{text:input.value}}));
      input.addEventListener('input',draft,{signal});
      input.addEventListener('keydown',event=>{
        if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();panel.querySelector('form').requestSubmit();}
      },{signal});
      panel.querySelectorAll('[data-command]').forEach(button=>button.addEventListener('click',()=>{
        input.value=window.LabUI?.language==='hy'?window.LabUI.t(button.dataset.command):button.dataset.command;
        draft();input.focus();
      },{signal}));
      panel.querySelector('form').addEventListener('submit',event=>{
        event.preventDefault();
        const text=input.value.trim();if(!text||panel.querySelector('[type="submit"]').disabled)return;
        const request=new CustomEvent('mascot-request',{bubbles:true,cancelable:true,detail:{text}});
        this.dispatchEvent(request);
        // The host cancels the event only after accepting it through the normal composer.
        if(request.defaultPrevented)this.closePanel(false);
      },{signal});
      window.addEventListener('resize',()=>this._positionPanel(),{signal});
    }
    openPanel(){
      this.dispatchEvent(new CustomEvent('mascot-open',{bubbles:true}));
      this._panel.showPopover();this.setAttribute('data-panel-open','');
      this._trigger.setAttribute('aria-expanded','true');
      this._positionPanel();this._question.focus();
    }
    closePanel(restoreFocus=false){
      this._panel.hidePopover();this.removeAttribute('data-panel-open');
      this._trigger.setAttribute('aria-expanded','false');
      if(restoreFocus)this._trigger.focus();
    }
    _positionPanel(){
      if(!this._panel?.matches(':popover-open'))return;
      const anchor=this.getBoundingClientRect(),box=this._panel.getBoundingClientRect();
      this._panel.style.left=Math.max(12,Math.min(anchor.right-box.width,innerWidth-box.width-12))+'px';
      this._panel.style.top=Math.max(80,anchor.top-box.height-10)+'px';
    }
    setAssistantState({blocked=false,busy=false,reply=false,demo=false,draft=''}){
      if(!this._panel)return;
      this._assistantState={blocked,busy,reply,demo};
      if(!this._panel.matches(':popover-open'))this._question.value=draft;
      this._question.disabled=busy;
      this._panel.querySelector('[type="submit"]').disabled=blocked;
      this._panel.querySelectorAll('[data-command]').forEach(button=>{button.disabled=blocked;button.hidden=reply;});
      this.updateLabels();this._positionPanel();
    }
    get _static(){return this._paused||this._motion.matches||document.hidden;}
    _rest(){this._show(this._static?'poster':this._processing?'scanning':'idle');}
    play(state){
      if(!this._static&&durations[state])this._show(state,true);
    }
    updateLabels(){
      if(!this._pause)return;
      const t=window.LabUI?.t|| (text=>text);
      const reduced=this._motion.matches;
      this._trigger.setAttribute('aria-label',t('Open Photonics AI assistant'));
      this._pause.disabled=reduced;
      this._pause.setAttribute('aria-pressed',String(this._paused||reduced));
      const label=reduced?'Mascot animation follows your reduced motion setting':this._paused?'Resume mascot animation':'Pause mascot animation';
      this._pause.setAttribute('aria-label',t(label));this._pause.title=t(label);
      this._pause.querySelector('span').textContent=t(this._paused&&!reduced?'Resume':'Pause');
      this._pause.querySelector('path').setAttribute('d',this._paused&&!reduced?'M4 2 13 8 4 14Z':'M4 3h3v10H4zM9 3h3v10H9z');
      if(this._panel){
        this._panel.setAttribute('aria-label',t('Photonics assistant'));
        this._panel.querySelectorAll('[data-label]').forEach(node=>node.textContent=t(node.dataset.label));
        this._panel.querySelectorAll('[data-name]').forEach(node=>node.setAttribute('aria-label',t(node.dataset.name)));
        const state=this._assistantState||{};
        this._question.placeholder=t(state.reply?'Reply to your lab…':'Ask about your lab or describe a task…');
        this._panel.querySelector('.mascot-panel-status').textContent=t(state.busy?'Following your current command':state.blocked?'Finish or cancel the current task before sending another.':state.reply?'Your answer continues this command':state.demo?'Demo mode: simulated lab data. Connect AI for free-form requests.':'Questions are read-only. Review paths before any movement.');
      }
    }
    async _show(state,restart=false){
      if(this._state===state&&!restart)return;
      clearTimeout(this._timer);this._timer=null;
      this._state=state;this.dataset.animation=state;
      const version=++this._version;
      const signal=this._lifecycle.signal;
      const base=this.getAttribute('asset-base')||'/static/mascot/';
      const src=base+'photonics-ai-'+state+'-256.'+(state==='poster'?'png':'gif');
      // Fetch each behavior only on demand. Fresh blob URLs restart cached GIFs
      // without redownloading them or relying on browser decoder cache behavior.
      try{
        if(!this._cache.has(state)){
          this._cache.set(state,fetch(src,{signal}).then(response=>{
            if(!response.ok)throw Error('Mascot asset unavailable');
            return response.blob();
          }).catch(error=>{this._cache.delete(state);throw error;}));
        }
        const blob=await this._cache.get(state);
        if(signal.aborted||version!==this._version)return;
        const url=URL.createObjectURL(blob);
        const old=this._url;this._url=url;
        const image=this._image.cloneNode(false);
        image.onload=()=>{
          image.onload=null;image.onerror=null;
          if(signal.aborted||version!==this._version)return;
          if(durations[state])this._timer=setTimeout(()=>this._rest(),durations[state]);
        };
        image.onerror=()=>{image.onload=null;image.onerror=null;if(version===this._version&&state!=='poster')this._show('poster');};
        image.src=url;this._image.replaceWith(image);this._image=image;
        if(old)URL.revokeObjectURL(old);
      }catch(error){
        if(!signal.aborted&&version===this._version&&state!=='poster')this._show('poster');
      }
    }
  }
  customElements.define('photonics-mascot',PhotonicsMascot);
})();
