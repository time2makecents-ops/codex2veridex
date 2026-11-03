/* Shared, local-first image controls for existing file preview surfaces. */
(() => {
  'use strict';
  const records = new Map();
  const empty = () => ({auto:false, remove_background:false, adjustments:{}, rotation:0});
  const clone = value => JSON.parse(JSON.stringify(value));
  const dirty = row => Boolean(row.formPending || row.recipe.auto || row.recipe.remove_background || row.recipe.rotation || row.recipe.crop || Object.values(row.recipe.adjustments).some(Boolean));
  const eligible = file => /\.(png|jpe?g|webp)$/i.test(file.name || '') && /^image\//.test(file.content_type || '');
  const id = () => crypto.randomUUID();
  const notify = message => showToast(message);
  function node(parent, tag, text, className) {
    const result = document.createElement(tag);
    if(text !== undefined) result.textContent = text;
    if(className) result.className = className;
    parent.append(result); return result;
  }
  function button(parent, text, action, className='') {
    const result = node(parent, 'button', text, className); result.type='button';
    result.addEventListener('click', () => Promise.resolve().then(action).catch(error => notify(error.message)));
    return result;
  }
  function payload(row) {
    return {...row.context, file_id:row.file.file_id, sha256:row.file.sha256};
  }
  function release(row) {
    if(row.url) URL.revokeObjectURL(row.url);
    row.url=''; row.recipe=empty(); row.beforeAuto=null; row.saveId=''; row.formPending=false;
  }
  function current(row) {
    return row.context.workspace_id === state.workspace?.workspace_id && row.context.session_id === state.session?.session_id && row.context.room_id === state.session?.active_room;
  }
  function redraw(row) { row.draw?.(); row.editorDraw?.(); }
  async function preview(row, options, flushForm=false) {
    if(row.busy && !flushForm) return;
    row.busy=true; row.workingBackground=Boolean(options.remove_background); redraw(row);
    try {
      const response=await fetch('/api/room/images/preview', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...payload(row), recipe:options})});
      if(!response.ok) { const value=await response.json(); throw new Error(value.error || 'Preview failed'); }
      const blob=await response.blob();
      if(!current(row)) throw new Error('The room changed; reopen the image.');
      if(row.url) URL.revokeObjectURL(row.url);
      row.url=URL.createObjectURL(blob); row.recipe=clone(options); row.saveId=''; row.formPending=false;
    } finally { row.busy=false; row.workingBackground=false; redraw(row); }
  }
  function reset(row) { release(row); redraw(row); }
  async function toggleAuto(row) {
    if(row.recipe.auto) {
      const previous=row.beforeAuto || empty();
      if(dirty({recipe:previous})) await preview(row, previous); else reset(row);
      row.beforeAuto=null;
    } else {
      const previous=clone(row.recipe);
      await preview(row, {...row.recipe, auto:true}); row.beforeAuto=previous;
    }
    redraw(row);
  }
  async function toggleBackground(row) {
    const options={...row.recipe,remove_background:!row.recipe.remove_background};
    if(dirty({recipe:options})) await preview(row,options); else reset(row);
  }
  async function save(row) {
    if(row.formPending) await row.applyForm();
    if(!dirty(row)) return row.file;
    if(!current(row)) throw new Error('The room changed; reopen the image.');
    row.busy=true;redraw(row);
    row.saveId ||= id();
    const result=await api('/api/room/images/save', {method:'POST', body:JSON.stringify({...payload(row), recipe:row.recipe, request_id:row.saveId, confirm:true})});
    const file={...result.file, source_session_id:state.session.session_id};
    release(row); row.file=file; row.originalUrl=artImageContentUrl(file); row.sendIds=new Map();
    if(!state.files.some(item=>item.file_id===file.file_id)) state.files.unshift(file);
    if(row.context.library==='session') state.selectedSessionFileId=file.file_id;
    if(row.context.library==='room') {
      if(state.session.active_room==='art_department') {
        state.artImages.unshift(file); state.selectedArtImageId=file.file_id;
      } else { state.roomFiles.unshift(file); state.selectedRoomFileId=file.file_id; }
    }
    renderFiles();
    if(row.context.library==='room') state.session.active_room==='art_department' ? renderArtGallery() : renderRoomFileLibrary();
    redraw(row); notify('Saved a separate edited copy.'); return file;
  }
  function dialog(title, className='image-tool-dialog') {
    const element=node(document.body, 'dialog', undefined, className);
    const header=node(element, 'header'); node(header, 'h2', title);
    return {element, header};
  }
  async function leave(library) {
    const row=records.get(library);
    if(!row || !dirty(row) && !row.busy) return true;
    if(row.busy) { notify('Wait for the image operation to finish.'); return false; }
    return new Promise(resolve=>{
      const {element, header}=dialog('Keep your image changes?');
      node(element, 'p', 'Save a separate copy, discard the unsaved preview, or keep editing.');
      const actions=node(element, 'div', undefined, 'image-tool-actions');
      const finish=value=>{element.close();element.remove();resolve(value);};
      const saveButton=button(actions, 'Save copy', async()=>{
        row.busy=true; redraw(row); saveButton.disabled=true;
        try { await save(row); finish(true); } catch(error) { notify(error.message); }
        finally {row.busy=false;saveButton.disabled=false;redraw(row);}
      }, 'primary-action');
      button(actions, 'Discard', ()=>{if(!row.busy){reset(row);finish(true);}});
      button(actions, 'Keep editing', ()=>{if(!row.busy)finish(false);});
      element.addEventListener('cancel', event=>{event.preventDefault();if(!row.busy)finish(false);});
      element.showModal();
    });
  }
  async function leaveAll() {
    for(const library of records.keys()) if(!await leave(library)) return false;
    for(const row of records.values()) {row.editor?.close();row.editor?.remove();release(row);}
    records.clear(); return true;
  }
  function openEditor(row) {
    if(row.editor?.open) {row.editor.focus();return;}
    const {element,header}=dialog('Edit image'); row.editor=element;
    const close=async()=>{if(await leave(row.context.library)){element.close();element.remove();row.editor=null;row.editorDraw=null;}};
    button(header,'Close',close); element.addEventListener('cancel',event=>{event.preventDefault();void close();});
    const layout=node(element,'div',undefined,'image-editor-layout');
    const stage=node(layout,'div',undefined,'image-editor-stage');
    const image=node(stage,'img');image.alt=row.file.name;
    let compare=false;
    const compareButton=button(stage,'Compare with original',()=>{compare=!compare;update();});
    const form=node(layout,'form',undefined,'image-editor-controls');
    form.addEventListener('submit',event=>event.preventDefault());
    const groups=[['Light',['exposure','brightness','highlights','shadows','contrast']],['Color',['saturation','warmth']],['Detail',['definition','sharpness']]];
    const inputs=new Map(), outputs=new Map();
    for(const [title,keys] of groups) {
      const fieldset=node(form,'fieldset');node(fieldset,'legend',title);
      for(const key of keys) {
        const label=node(fieldset,'label',key[0].toUpperCase()+key.slice(1));
        const input=node(label,'input'); input.type='range'; input.min=-100;input.max=100;input.step=1;input.value=row.recipe.adjustments[key]||0;
        const output=node(label,'output',input.value);outputs.set(key,output);
        input.addEventListener('input',()=>{output.textContent=input.value;row.formPending=true;update();row.draw?.();});
        input.setAttribute('aria-label',key);inputs.set(key,input);
      }
    }
    const crop=node(form,'fieldset');node(crop,'legend','Crop and rotate');
    const cropInputs=new Map();
    for(const [key,title,fallback] of [['left_percent','Left',0],['top_percent','Top',0],['right_percent','Right',100],['bottom_percent','Bottom',100]]) {
      const label=node(crop,'label',title+' (%)'),input=node(label,'input');input.type='number';input.min=0;input.max=100;input.step=1;input.value=row.recipe.crop?.[key]??fallback;cropInputs.set(key,input);
    }
    const label=node(crop,'label','Rotation'),rotation=node(label,'select');
    for(const degrees of [0,90,180,270]) {const option=node(rotation,'option',degrees+'°');option.value=degrees;}
    rotation.value=row.recipe.rotation;
    const actions=node(form,'div',undefined,'image-tool-actions');
    row.applyForm=async()=>{
      const adjustments=Object.fromEntries([...inputs].map(([key,input])=>[key,Number(input.value)]));
      const edges=Object.fromEntries([...cropInputs].map(([key,input])=>[key,Number(input.value)]));
      const options={...row.recipe,adjustments,rotation:Number(rotation.value)};
      if(edges.left_percent||edges.top_percent||edges.right_percent!==100||edges.bottom_percent!==100) options.crop=edges; else delete options.crop;
      compare=false;await preview(row,options,true);
    };
    const apply=button(actions,'Apply preview',()=>row.applyForm(),'primary-action');
    for(const input of [...inputs.values(),...cropInputs.values(),rotation]) {
      input.addEventListener('input',()=>{row.formPending=true;update();row.draw?.();});
      input.addEventListener('change',()=>{row.formPending=true;void row.applyForm().catch(error=>notify(error.message));});
    }
    const saveButton=button(actions,'Save copy',async()=>{
      row.busy=true;redraw(row);try{await save(row);}finally{row.busy=false;redraw(row);}
    });
    const resetButton=button(actions,'Reset preview',()=>reset(row));
    const status=node(form,'p',undefined,'image-tool-status');status.setAttribute('role','status');
    function update(){
      image.src=compare?row.originalUrl:(row.url||row.originalUrl);
      compareButton.textContent=compare?'Show edited preview':'Compare with original';
      status.textContent=row.busy?'Preparing image…':dirty(row)?'Unsaved preview. Save copy to keep this version.':'Original or saved copy. Your source is unchanged.';
      apply.disabled=row.busy;saveButton.disabled=row.busy||!dirty(row);
      resetButton.disabled=row.busy;
      for(const [key,input] of inputs){input.disabled=row.busy;if(!row.formPending){input.value=row.recipe.adjustments[key]||0;outputs.get(key).textContent=input.value;}}
      for(const [key,input] of cropInputs){input.disabled=row.busy;if(!row.formPending)input.value=row.recipe.crop?.[key]??(key==='right_percent'||key==='bottom_percent'?100:0);}
      rotation.disabled=row.busy;if(!row.formPending)rotation.value=row.recipe.rotation;
    }
    row.editorDraw=update;update();element.showModal();
  }
  function openSend(row) {
    const {element,header}=dialog('Send image to a room');
    button(header,'Close',()=>{if(!row.busy){element.close();element.remove();}});
    const workspaceLabel=node(element,'label','Workspace'),workspaces=node(workspaceLabel,'select');
    const candidates=[...state.workspaces];if(!candidates.some(item=>item.workspace_id===state.workspace.workspace_id)) candidates.unshift(state.workspace);
    for(const item of candidates) {const option=node(workspaces,'option',item.label||item.title||item.workspace_id);option.value=item.workspace_id;}
    workspaces.value=state.workspace.workspace_id;
    const roomLabel=node(element,'label','Room'),rooms=node(roomLabel,'select');
    for(const room of state.rooms.filter(room=>room.id!=='lobby'&&room.is_active!==false)) {const option=node(rooms,'option',room.title);option.value=room.id;}
    if([...rooms.options].some(option=>option.value===state.session.active_room)) rooms.value=state.session.active_room;
    node(element,'p','Adds a copy to the selected room’s files. You stay here.');
    const send=button(element,dirty(row)?'Save copy and send':'Send',async()=>{
      row.busy=true;send.disabled=true;workspaces.disabled=rooms.disabled=true;redraw(row);
      try {
        if(dirty(row)) await save(row);
        send.textContent='Send';
        const target=workspaces.value+'/'+rooms.value;
        if(!row.sendIds.has(target)) row.sendIds.set(target,id());
        await api('/api/room/images/send',{method:'POST',body:JSON.stringify({...payload(row),request_id:row.sendIds.get(target),target_workspace_id:workspaces.value,target_room_id:rooms.value,confirm:true})});
        element.close();element.remove();notify('Image added to '+workspaces.selectedOptions[0].textContent+' / '+rooms.selectedOptions[0].textContent+'.');
      } catch(error) {notify(error.message+(dirty(row)?'':' Your saved image is available; you can retry Send.'));}
      finally{row.busy=false;send.disabled=false;workspaces.disabled=rooms.disabled=false;redraw(row);}
    },'primary-action');send.disabled=!rooms.options.length;
    element.addEventListener('cancel',event=>{if(row.busy)event.preventDefault();else element.remove();});element.showModal();
  }
  function mount(file,library,hero,actions) {
    if(!eligible(file)) return;
    let row=records.get(library);
    const context={workspace_id:state.workspace.workspace_id,session_id:state.session.session_id,room_id:state.session.active_room,library};
    if(!row || row.file.file_id!==file.file_id || !current(row)) {
      if(row) release(row);
      row={file,context,recipe:empty(),originalUrl:artImageContentUrl(file),url:'',sendIds:new Map(),busy:false}; records.set(library,row);
    }
    const originalActions=[...actions.children];
    const touch=button(actions,'Touch up',()=>toggleAuto(row));
    const background=button(actions,'Remove background',()=>toggleBackground(row));
    const edit=button(actions,'Edit',()=>openEditor(row));
    const saveButton=button(actions,'Save copy',async()=>{row.busy=true;redraw(row);try{await save(row);}finally{row.busy=false;redraw(row);}});
    const send=button(actions,'Send',()=>openSend(row));
    const status=node(hero,'p',undefined,'image-tool-status');status.setAttribute('role','status');
    row.draw=()=>{
      const image=hero.querySelector('img');if(image){image.src=row.url||row.originalUrl;image.setAttribute('data-background-removed',String(Boolean(row.recipe.remove_background)));}
      touch.textContent=row.recipe.auto?'Revert':'Touch up';
      background.textContent=row.recipe.remove_background?'Restore background':'Remove background';
      touch.disabled=background.disabled=edit.disabled=send.disabled=row.busy;saveButton.disabled=row.busy||!dirty(row);
      status.textContent=row.busy?(row.workingBackground?'Removing background locally…':'Preparing image…'):dirty(row)?(row.recipe.remove_background?'Unsaved transparent preview — check the edges, then Save copy.':'Unsaved preview — Save copy to keep this version.') :'';
      for(const action of originalActions) {
        if(action.textContent==='Open original')continue;
        action.setAttribute('aria-disabled',String(dirty(row)||row.busy));
        if(action.tagName==='BUTTON') action.disabled=dirty(row)||row.busy||state.selectedFiles.has(row.file.file_id);
      }
    };
    for(const action of originalActions) if(action.tagName==='A' && action.textContent!=='Open original') action.addEventListener('click',event=>{if(dirty(row)||row.busy){event.preventDefault();notify('Save copy or Revert before downloading.');}});
    row.draw();
  }
  window.addEventListener('beforeunload',event=>{if([...records.values()].some(row=>dirty(row)||row.busy)){event.preventDefault();event.returnValue='';}});
  for(const [dialogId,library] of [['session-files-dialog','session'],['room-file-dialog','room'],['art-gallery-dialog','room']]) {
    document.getElementById(dialogId).addEventListener('cancel',event=>{
      const row=records.get(library);if(row&&(dirty(row)||row.busy)){event.preventDefault();void leave(library).then(ok=>{if(ok)document.getElementById(dialogId).close();});}
    });
  }
  window.ImagePreviewTools={mount,leave,leaveAll};
})();
