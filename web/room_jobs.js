(() => {
  const surface=document.querySelector('.room-workspace [data-overview]');
  surface.classList.add('room-job-workspace');
  surface.innerHTML='<nav data-job-tabs aria-label="Workspace jobs"></nav><section data-active-job></section>';
  const tabs=surface.querySelector('[data-job-tabs]'),activePane=surface.querySelector('[data-active-job]');
  const popup=document.createElement('section');popup.className='room-jobs-popup';popup.hidden=true;popup.setAttribute('role','dialog');popup.setAttribute('aria-label','Room jobs');
  popup.innerHTML='<section class="room-jobs-list-panel"><header><h3>Room jobs</h3><label>Sort by<select data-sort aria-label="Sort jobs by"></select></label><button data-close type="button" aria-label="Close Jobs">&times;</button></header><div data-list aria-label="Job cards"></div><footer><button data-refresh type="button">Refresh jobs</button></footer></section><section data-detail class="room-jobs-detail" aria-label="Job details" hidden></section>';
  document.body.append(popup);
  const list=popup.querySelector('[data-list]'),detail=popup.querySelector('[data-detail]'),sort=popup.querySelector('[data-sort]');
  const text=(parent,tag,value)=>{const node=document.createElement(tag);node.textContent=value;parent.append(node);return node;};
  const button=(parent,title,handler)=>{const node=text(parent,'button',title);node.type='button';node.onclick=handler;return node;};
  [['newest','Newest'],['oldest','Oldest'],['name','Image name A-Z'],['name-desc','Image name Z-A'],['status','Type: A-Z'],...['completed','draft','running','queued','submitting','cancel_requested','failed','interrupted','canceled'].map(value=>['type:'+value,'Type: '+value.replaceAll('_',' ').replace(/^./,letter=>letter.toUpperCase())+' first']),['origin','Source']].forEach(([value,label])=>sort.add(new Option(label,value)));
  let scope='',rows=[],workspaceJobs=[],currentDraft=null,selected='',active='',draftId='',messageSignature='';
  const pending=new Set();
  const key=()=>`${state.workspace?.workspace_id}/${state.session?.session_id}/${state.session?.active_room}`;
  const context=()=>({workspace_id:state.workspace.workspace_id,session_id:state.session.session_id});
  const call=(action,extra={})=>api('/api/room/jobs',{method:'POST',body:JSON.stringify({...context(),action,...extra})});
  const label=job=>`Job #${String(job.number).padStart(6,'0')}`;
  const name=file=>file.display_name || file.name || 'Image';
  const title=job=>job.files?.length?name(job.files[0]):job.brief.output_name || job.title;
  const source=job=>job.origin==='art_studio'?'Art Studio':'Chat';
  const status=job=>job.save_draft_pending?'Stopping and saving draft...':job.status.replaceAll('_',' ');
  const fileUrl=(file,download=false)=>'/api/files/content?'+new URLSearchParams({...context(),session_id:file.source_session_id || state.session.session_id,file_id:file.file_id,...(download?{download:'1'}:{})});
  function position(){const rail=document.querySelector('.rail')?.getBoundingClientRect();const bar=document.querySelector('.room-workspace .video-workspace-bar')?.getBoundingClientRect();const left=Math.max(8,Math.min(rail?.right || 8,innerWidth-320));const top=Math.min(bar?.bottom || 90,Math.max(8,innerHeight-220))+8;popup.style.left=left+'px';popup.style.top=top+'px';popup.style.maxWidth=(innerWidth-left-8)+'px';popup.style.height=Math.max(180,Math.min(744,innerHeight-top-8))+'px';popup.classList.toggle('is-narrow',innerWidth-left-8<640);}
  function closeJobs(){popup.hidden=true;detail.hidden=true;popup.classList.remove('has-detail');jobsButton.setAttribute('aria-expanded','false');}
  const jobsButton=button(document.querySelector('.room-workspace [data-actions]'),'Jobs',()=>{if(!popup.hidden){closeJobs();return;}popup.hidden=false;jobsButton.setAttribute('aria-expanded','true');position();refresh();});
  jobsButton.setAttribute('aria-expanded','false');
  popup.querySelector('[data-close]').onclick=closeJobs;popup.querySelector('[data-refresh]').onclick=()=>refresh(true);
  window.addEventListener('resize',position);
  const mode=document.createElement('div');mode.className='room-precreation-mode';mode.hidden=true;
  const modeText=text(mode,'span','');document.querySelector('.room-floating-chat .composer-wrap').prepend(mode);
  function normalChat(){draftId='';mode.hidden=true;}
  function keepEditing(id){draftId=id;mode.hidden=false;modeText.textContent='Pre-creation: your messages refine this draft. ';window.roomWorkspace.openChat();}
  button(mode,'Return to normal chat',normalChat);
  const preview=document.createElement('dialog');preview.className='room-image-preview';preview.setAttribute('aria-label','Image preview');document.body.append(preview);
  function openImage(file){preview.replaceChildren();button(preview,'Close',()=>preview.close());const image=document.createElement('img');image.src=fileUrl(file);image.alt=name(file);preview.append(image);text(preview,'p',name(file));const download=text(preview,'a','Download');download.href=fileUrl(file,true);download.download=name(file);if(!preview.open)preview.showModal();}
  const confirmation=document.createElement('dialog');confirmation.className='room-job-confirmation';confirmation.setAttribute('aria-label','Send image to room');document.body.append(confirmation);
  let confirmationRow=null,confirmationScope='',confirmationRetry=false,confirmBusy=false,confirmationNameInput=null;
  async function noSend(){if(confirmBusy)return;const row=confirmationRow;
    if(row&&confirmationScope===scope&&row.status==='draft'&&confirmationNameInput?.value!==row.brief.output_name){try{await call('update',{room_job_id:row.request_id,version:row.version,brief:{output_name:confirmationNameInput.value}});}catch(e){showError(e.message);}}
    if(confirmation.open)confirmation.close();if(row&&confirmationScope===scope)keepEditing(row.request_id);confirmationRow=null;
  }
  confirmation.addEventListener('cancel',event=>{event.preventDefault();noSend();});
  async function requestConfirmation(row,retry=false){
    try{const expected=scope;const result=await call('prepare_send',{room_job_id:row.request_id});if(expected!==scope)return;const job=result.job;
      if(row.version && row.version!==job.version){showError('The brief changed. Review its latest version before sending.');openDetails(job);return;}
      confirmationRow=job;confirmationScope=scope;confirmationRetry=retry;confirmBusy=false;confirmation.replaceChildren();
      text(confirmation,'h3','Do you want to send to room?');text(confirmation,'p',`${label(job)} \u00b7 ${job.brief.operation==='edit'?'Edit image':'Image production'}`);text(confirmation,'p',job.brief.prompt);
      const field=text(confirmation,'label','File name');const input=document.createElement('input');input.value=job.brief.output_name || '';input.maxLength=120;input.dataset.outputName='';input.disabled=job.status!=='draft';confirmationNameInput=input;field.append(input);
      for(const file of job.references || []){const image=document.createElement('img');image.src=fileUrl(file);image.alt='Source: '+name(file);image.className='confirmation-reference';confirmation.append(image);}
      const error=text(confirmation,'p','');error.setAttribute('role','alert');
      const yes=button(confirmation,'Yes',async()=>{if(confirmBusy||confirmationScope!==scope)return;confirmBusy=true;yes.disabled=true;no.disabled=true;input.disabled=true;
        try{let current=confirmationRow;if(input.value!==current.brief.output_name){current=(await call('update',{room_job_id:current.request_id,version:current.version,brief:{output_name:input.value}})).job;confirmationRow=current;}
          const result=await call(confirmationRetry?'retry':'submit',{room_job_id:current.request_id,version:current.version,confirm:true});
          if(confirmationScope!==scope)return;normalChat();active=result.job.request_id;confirmation.close();confirmationRow=null;await refresh(true);
        }catch(e){error.textContent=e.message;await refresh();}finally{confirmBusy=false;yes.disabled=false;no.disabled=false;input.disabled=job.status!=='draft';}
      });
      const no=button(confirmation,'No, keep editing',noSend);if(!confirmation.open)confirmation.showModal();input.focus();
    }catch(e){showError(e.message);}
  }
  async function perform(action,row){if(pending.has(row.request_id))return;pending.add(row.request_id);const expected=scope;
    try{await call(action,{room_job_id:row.request_id,version:row.version});if(expected===scope){if(action==='save_draft')normalChat();await refresh(true);}}
    catch(e){showError(e.message);}finally{pending.delete(row.request_id);renderMessages();}
  }
  function sortedRows(){const result=[...rows];const compare=(a,b)=>{const choice=sort.value;if(choice==='name'||choice==='name-desc')return title(a).localeCompare(title(b),undefined,{numeric:true})*(choice==='name-desc'?-1:1);if(choice.startsWith('type:')){const preferred=choice.slice(5);return Number(b.status===preferred)-Number(a.status===preferred)||a.status.localeCompare(b.status)||String(b.created_at).localeCompare(String(a.created_at));}if(choice==='status')return a.status.localeCompare(b.status);if(choice==='origin')return source(a).localeCompare(source(b));return String(a.created_at).localeCompare(String(b.created_at))*(choice==='oldest'?1:-1);};return result.sort((a,b)=>compare(a,b)||b.number-a.number);}
  function drawList(){list.replaceChildren();if(!rows.length)text(list,'p','No saved or submitted jobs yet.');for(const row of sortedRows()){
    const card=button(list,'',()=>{selected=row.request_id;drawList();});card.className='room-job-card';card.setAttribute('aria-label',`${label(row)} \u00b7 ${title(row)} \u00b7 ${status(row)}`);card.setAttribute('aria-pressed',String(selected===row.request_id));
    const thumb=document.createElement('img');if(row.files?.length)thumb.src=fileUrl(row.files[0]);else if(row.references?.length)thumb.src=fileUrl(row.references[0]);else thumb.hidden=true;thumb.alt='Job thumbnail';card.append(thumb);
    const info=document.createElement('span');info.className='room-job-card-info';text(info,'strong',title(row));text(info,'small',`${label(row)} \u00b7 ${new Date(row.created_at).toLocaleDateString()}`);text(info,'small',`${source(row)} \u00b7 ${status(row)}`);card.append(info);
    card.ondblclick=()=>openDetails(row);card.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();openDetails(row);}};
  }}
  sort.onchange=()=>{try{localStorage.setItem('veridex-job-sort:'+scope,sort.value);}catch{}drawList();};
  function hasEdits(container){return Boolean(container.querySelector('form[data-dirty="true"]'));}
  function openDetails(row){if(!detail.hidden&&hasEdits(detail)&&detail.dataset.requestId!==row.request_id){showError('Save your brief changes before opening another job.');return;}selected=row.request_id;popup.hidden=false;detail.hidden=false;popup.classList.add('has-detail');jobsButton.setAttribute('aria-expanded','true');drawDetail(row);drawList();position();}
  async function createRevision(row,operation){try{const result=await call('create',{prompt:row.brief.prompt,parent_request_id:row.request_id,operation,client_id:crypto.randomUUID()});currentDraft=result.job;keepEditing(result.job.request_id);await sendMessage('Keep editing');}catch(e){showError(e.message);}}
  function technical(container,row){const disclosure=document.createElement('details');container.append(disclosure);text(disclosure,'summary','Technical details');text(disclosure,'p',`${row.request_id}\nOrigin session: ${row.session_id}`);for(const attempt of row.attempts)text(disclosure,'p',attempt.attempt_id);for(const file of row.files || [])text(disclosure,'p',`SHA-256: ${file.sha256}\n${file.path || ''}`);}
  function actions(container,row){const bar=document.createElement('div');bar.className='room-job-actions';container.append(bar);
    if(['submitting','queued','running','cancel_requested'].includes(row.status))button(bar,'Cancel production',()=>perform('cancel',row)).disabled=row.status==='cancel_requested';
    if(row.status!=='completed')button(bar,'Save as draft',()=>perform('save_draft',row)).disabled=Boolean(row.save_draft_pending);
    if(['failed','canceled','interrupted'].includes(row.status))button(bar,'Retry',()=>requestConfirmation(row,true));
    if(row.status==='completed'){button(bar,row.accepted?'Accepted':'Accept',()=>perform('accept',row)).disabled=Boolean(row.accepted);button(bar,'Revise',()=>createRevision(row,'edit'));button(bar,'Create variants',()=>createRevision(row,'generate'));button(bar,'Resize/export',()=>createRevision(row,'resize'));button(bar,'Compare versions',async()=>{const files=[...row.files,...(rows.find(other=>other.request_id===row.parent_request_id)?.files || [])];drawImages(container,files);});}
    button(bar,'Ask Systems',()=>{openContainedChat('system');document.getElementById('contained-chat-input').value=`What happened to request ${row.request_id}?`;});
  }
  function drawDetail(row){detail.replaceChildren();detail.dataset.requestId=row.request_id;const header=document.createElement('header');text(header,'h3',label(row));button(header,'Close details',()=>{detail.hidden=true;popup.classList.remove('has-detail');position();});detail.append(header);text(detail,'h4',title(row));text(detail,'p',`${source(row)} \u00b7 ${status(row)}`);if(row.error)text(detail,'p',row.error);
    if(row.history_kind==='imported_result')text(detail,'p','Imported Art Studio result. Original job settings may be unavailable.');
    const original=document.createElement('details');detail.append(original);text(original,'summary','Original instructions');text(original,'p',row.original_instructions);
    if(row.status==='draft')drawBrief(detail,row);else{text(detail,'p',row.brief.prompt);actions(detail,row);}
    text(detail,'h4','Attempts');row.attempts.forEach((attempt,index)=>text(detail,'p',`Attempt ${index+1}: ${attempt.status} \u00b7 ${attempt.route?.provider || ''} ${attempt.route?.model || ''}`));
    drawImages(detail,row.files || []);technical(detail,row);
  }
  function drawBrief(container,row){const form=document.createElement('form');container.append(form);form.onsubmit=e=>e.preventDefault();
    const field=(title,value,tag='input')=>{const label=text(form,'label',title);const input=document.createElement(tag);input.value=value;label.append(input);input.oninput=()=>form.dataset.dirty='true';return input;};
    const outputName=field('File name',row.brief.output_name || '');outputName.maxLength=120;
    const prompt=field('Image brief',row.brief.prompt,'textarea');prompt.rows=4;
    const aspect=field('Aspect',row.brief.aspect,'select');[...new Set(['square','landscape','portrait',row.brief.aspect])].forEach(value=>aspect.add(new Option(value,value)));aspect.value=row.brief.aspect;
    const variants=field('Variants',row.brief.variants);variants.type='number';variants.min=1;variants.max=4;
    const refs=[];for(const file of row.references || []){const label=text(form,'label','Use reference '+name(file));const input=document.createElement('input');input.type='checkbox';input.checked=true;input.onchange=()=>form.dataset.dirty='true';label.prepend(input);refs.push({input,id:file.file_id});}
    let width,height,format;if(['resize','convert'].includes(row.brief.operation)){width=field('Width in pixels',row.brief.options.width || '');height=field('Height in pixels',row.brief.options.height || '');width.type=height.type='number';width.min=height.min=64;width.max=height.max=5000;format=field('Format',row.brief.options.format || 'PNG','select');['PNG','JPEG','WEBP'].forEach(value=>format.add(new Option(value,value)));format.value=row.brief.options.format || 'PNG';}
    const save=async()=>{if(form.dataset.dirty!=='true')return row;const result=await call('update',{room_job_id:row.request_id,version:row.version,brief:{...row.brief,output_name:outputName.value,prompt:prompt.value,aspect:aspect.value,variants:Number(variants.value),source_file_ids:refs.filter(ref=>ref.input.checked).map(ref=>ref.id),options:width?{...row.brief.options,width:width.value?Number(width.value):undefined,height:height.value?Number(height.value):undefined,format:format.value}:row.brief.options}});form.dataset.dirty='false';return result.job;};
    const safely=handler=>async()=>{try{await handler(await save());}catch(e){showError(e.message);}};
    button(form,'Save changes',safely(async()=>refresh(true)));button(form,'Send to room',safely(job=>requestConfirmation(job)));button(form,'Keep editing',safely(job=>keepEditing(job.request_id)));button(form,'Save as draft',safely(job=>perform('save_draft',job)));
  }
  function drawImages(container,files){container.querySelector('[data-results]')?.remove();const results=document.createElement('section');results.dataset.results='';container.append(results);
    for(const file of files){const figure=document.createElement('figure');const image=document.createElement('img');image.src=fileUrl(file);image.alt=name(file);image.onclick=()=>openImage(file);figure.append(image);button(figure,name(file),()=>openImage(file)).className='room-image-name';text(figure,'small',`${formatBytes(file.size)} \u00b7 Artifact #${file.artifact_number}`);
      const download=text(figure,'a','Download');download.href=fileUrl(file,true);download.download=name(file);
      const renameLabel=text(figure,'label','File name');const rename=document.createElement('input');rename.value=name(file);rename.maxLength=120;renameLabel.append(rename);
      button(figure,'Rename',async()=>{try{await api('/api/art/images/rename',{method:'POST',body:JSON.stringify({...context(),file_id:file.file_id,name:rename.value})});await refresh(true);if(window.loadArtImages)await loadArtImages();}catch(e){showError(e.message);}});results.append(figure);
    }
  }
  function drawWorkspace(){tabs.replaceChildren();if(!workspaceJobs.some(job=>job.request_id===active))active=workspaceJobs[0]?.request_id || '';
    for(const row of workspaceJobs){const tab=button(tabs,`${label(row)} \u00b7 ${title(row)}`,()=>{if(hasEdits(activePane)&&active!==row.request_id){showError('Save your brief changes before switching jobs.');return;}active=row.request_id;drawWorkspace();});tab.setAttribute('aria-pressed',String(active===row.request_id));}
    const row=workspaceJobs.find(job=>job.request_id===active);if(hasEdits(activePane))return;activePane.replaceChildren();if(!row){text(activePane,'h3','Workspace');text(activePane,'p','No active jobs. Prepare an image in chat or Art Studio, or open Jobs for saved work.');return;}
    text(activePane,'h3',`${label(row)} \u00b7 ${title(row)}`);text(activePane,'p',`${source(row)} \u00b7 ${status(row)}`);if(row.error)text(activePane,'p',row.error);
    if(row.status==='draft'){drawBrief(activePane,row);return;}
    const progress=document.createElement('progress');progress.max=100;if(row.progress)progress.value=row.progress;activePane.append(progress);text(activePane,'p',row.brief.prompt);actions(activePane,row);
    for(const file of row.references || []){const image=document.createElement('img');image.className='workspace-reference';image.src=fileUrl(file);image.alt='Source: '+name(file);activePane.append(image);}
  }
  async function refresh(force=false){if(!state.workspace||!state.session)return;const expected=scope;try{const result=await api('/api/room/jobs?'+new URLSearchParams(context()));if(expected!==scope)return;
    rows=result.jobs || [];workspaceJobs=result.workspace_jobs || [];currentDraft=result.current_draft || null;drawList();drawWorkspace();const job=rows.find(row=>row.request_id===selected);if(job&&!detail.hidden&&!hasEdits(detail)&&(force===true||!detail.contains(document.activeElement)))drawDetail(job);
    if(!state.sending&&!state.uploading){const data=await api('/api/messages?'+new URLSearchParams(context()));if(expected!==scope||state.sending)return;const signature=(data.messages || []).map(message=>message.message_id).join('/');if(signature!==messageSignature){messageSignature=signature;state.messages=data.messages || [];renderMessages();}}
  }catch(e){if(expected===scope)showError(e.message);}}
  window.renderRoomJobMessage=(row,article)=>{if(!row.room_job_id)return;const controls=document.createElement('div');controls.className='room-job-actions';article.append(controls);
    button(controls,'Open request',async()=>{if(row.room&&row.room!==state.session?.active_room)await navigateToRoom(row.room);try{const result=await call('get',{room_job_id:row.room_job_id});openDetails(result.job);}catch(e){showError(e.message);}});
    const latest=Math.max(row.image_draft_version || 0,...state.messages.filter(message=>message.room_job_id===row.room_job_id).map(message=>message.image_draft_version || 0));const job=rows.find(job=>job.request_id===row.room_job_id) || (currentDraft?.request_id===row.room_job_id?currentDraft:null);
    if(row.image_draft&&row.room===state.session?.active_room&&row.image_draft_version===latest&&(!job||(job.status==='draft'&&job.version===row.image_draft_version))){button(controls,'Send to room',()=>requestConfirmation({request_id:row.room_job_id,version:row.image_draft_version}));button(controls,'Keep editing',()=>keepEditing(row.room_job_id));button(controls,'Save as draft',()=>perform('save_draft',{request_id:row.room_job_id,version:row.image_draft_version}));}
  };
  window.roomJobs={draftId:()=>draftId,refresh,confirm:requestConfirmation};
  window.renderRoomJobs=()=>{if(key()!==scope){scope=key();rows=[];workspaceJobs=[];currentDraft=null;selected='';active='';normalChat();closeJobs();if(confirmation.open)confirmation.close();confirmationRow=null;if(preview.open)preview.close();try{sort.value=localStorage.getItem('veridex-job-sort:'+scope) || 'newest';}catch{sort.value='newest';}drawList();drawWorkspace();refresh();}};
  window.renderRoomJobs();setInterval(refresh,2500);
})();
