(() => {
  const main = document.getElementById('chat-panel');
  const messages = document.getElementById('messages');
  const composer = main.querySelector('.composer-wrap');
  const actions = document.getElementById('room-file-actions');
  const workspace = document.createElement('section');
  workspace.className = 'video-workspace'; workspace.hidden = true;
  workspace.setAttribute('aria-label','Video Production workspace');
  workspace.innerHTML = `<header class="video-workspace-bar"><div><span class="eyebrow">VIDEO PRODUCTION</span><h2>Media workspace</h2></div><div data-actions></div><button data-chat type="button">Chat with Beta</button></header>
  <div class="video-workspace-body"><aside class="video-library"><div class="video-library-controls"><input data-search type="search" placeholder="Search room media" aria-label="Search room media"><select data-filter aria-label="Media type"><option value="all">All files</option><option value="video">Videos</option><option value="audio">Audio</option><option value="image">Images</option><option value="document">Documents</option><option value="export">Exports</option></select><button data-view type="button" aria-pressed="false">List view</button><button data-refresh type="button">Refresh</button></div><p data-count></p><div data-gallery class="video-gallery" aria-label="Room media"></div><button data-more type="button" hidden>Show more</button><button data-cancel-upload type="button" hidden>Cancel upload</button></aside>
  <section class="video-preview" aria-label="Source preview"><div class="video-preview-heading"><strong data-name>Select a file to preview</strong><button data-hide-gallery type="button">Hide gallery</button></div><div data-stage class="video-player-stage"><p>Add footage, audio, images, or documents using Add files above.</p></div><p data-details></p><div data-file-actions class="video-file-actions"></div><p data-notice role="status" aria-live="polite"></p></section></div>
  <input data-room-upload type="file" multiple hidden>`;
  main.querySelector('.workspace-toolbar').after(workspace);
  const chat = document.createElement('section');chat.className='video-floating-chat';chat.hidden=true;chat.setAttribute('aria-label','Beta chat');
  chat.innerHTML='<header data-drag><strong>Beta · Video Production</strong><button data-close type="button" aria-label="Close Beta chat">Close</button></header>';
  document.body.append(chat);
  const attach = document.createElement('button');attach.type='button';attach.textContent='Attach';attach.title='Attach files to the next chat message';attach.hidden=true;
  document.getElementById('composer').prepend(attach);
  attach.onclick=()=>document.getElementById('file-input').click();
  const q=s=>workspace.querySelector(s);
  let scope='', rows=[], selected='', loading=0, generation=0, active=false, limit=60, request=null;
  let listView=false;
  const key=()=>`${state.workspace?.workspace_id}/${state.session?.session_id}`;
  const context=()=>({workspace_id:state.workspace.workspace_id,session_id:state.session.session_id});
  const current=()=>active && state.session?.active_room==='video_production' && key()===scope;
  const type=file=>String(file.content_type||'').split('/')[0];
  const url=file=>`/api/files/content?${new URLSearchParams({workspace_id:state.workspace.workspace_id,session_id:file.source_session_id||state.session.session_id,file_id:file.file_id})}`;
  const notice=text=>{q('[data-notice]').textContent=text;};
  function openChat(){chat.hidden=false;document.getElementById('message-input').focus();}
  function closeChat(){chat.hidden=true;q('[data-chat]').focus();}
  q('[data-chat]').onclick=openChat;chat.querySelector('[data-close]').onclick=closeChat;
  chat.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();closeChat();}});
  attach.addEventListener('keydown',event=>event.stopPropagation());
  let drag;
  chat.querySelector('[data-drag]').addEventListener('pointerdown',event=>{
    if(event.target.closest('button')||innerWidth<760)return;
    const rect=chat.getBoundingClientRect();drag={x:event.clientX-rect.left,y:event.clientY-rect.top};event.currentTarget.setPointerCapture(event.pointerId);
  });
  chat.querySelector('[data-drag]').addEventListener('pointermove',event=>{
    if(!drag)return;chat.style.left=Math.max(0,Math.min(innerWidth-chat.offsetWidth,event.clientX-drag.x))+'px';chat.style.top=Math.max(0,Math.min(innerHeight-60,event.clientY-drag.y))+'px';chat.style.right='auto';chat.style.bottom='auto';
  });
  chat.querySelector('[data-drag]').addEventListener('pointerup',()=>drag=null);
  chat.querySelector('[data-drag]').addEventListener('lostpointercapture',()=>drag=null);
  window.addEventListener('resize',()=>{
    if(chat.hidden||!chat.style.left||innerWidth<760)return;
    chat.style.left=Math.max(0,Math.min(parseFloat(chat.style.left),innerWidth-chat.offsetWidth))+'px';
    chat.style.top=Math.max(0,Math.min(parseFloat(chat.style.top)||0,innerHeight-60))+'px';
  });
  function preview(){
    const file=rows.find(row=>row.file_id===selected);const stage=q('[data-stage]');
    stage.querySelectorAll('video,audio').forEach(media=>media.pause());stage.replaceChildren();q('[data-file-actions]').replaceChildren();
    q('[data-name]').textContent=file?.name||'Select a file to preview';q('[data-details]').textContent='';
    if(!file){stage.textContent='Choose a room file, or use Add files to import media.';return;}
    const kind=type(file);let element;
    if(['video','audio'].includes(kind)){
      element=document.createElement(kind);element.controls=true;element.preload='metadata';element.src=url(file);
      element.addEventListener('loadedmetadata',()=>{if(Number.isFinite(element.duration))q('[data-details]').textContent+=` · ${element.duration.toFixed(1)} seconds`;});
      element.addEventListener('error',()=>notice('This browser cannot play this file. Try Open in VLC, or convert a copy with HandBrake in Production tools.'));
    }else if(kind==='image'){element=document.createElement('img');element.src=url(file);element.alt=file.name;}
    else{element=document.createElement('p');element.textContent='Use Open original to view this document.';}
    stage.append(element);q('[data-details]').textContent=`${file.content_type||'File'} · ${formatBytes(file.size||0)} · Artifact #${file.artifact_number||'—'}`;
    for(const [label,download] of [['Open original',false],['Download',true]]){
      const link=document.createElement('a');link.textContent=label;link.href=url(file);if(download)link.download=file.name;else{link.target='_blank';link.rel='noopener';}q('[data-file-actions]').append(link);
    }
    const chatButton=document.createElement('button');chatButton.type='button';chatButton.textContent='Attach to chat';chatButton.onclick=async()=>{await attachRoomFile(file);if(current())openChat();};q('[data-file-actions]').append(chatButton);
    if(['video','audio'].includes(kind)){
      const vlc=document.createElement('button');vlc.type='button';vlc.textContent='Open in VLC';vlc.onclick=async()=>{
        if(!window.confirm('Play this file in VLC on the Veridex computer?'))return;
        try{const result=await api('/api/room/files/open-vlc',{method:'POST',body:JSON.stringify({...context(),file_id:file.file_id,confirm:true})});notice(result.status==='launched'?'VLC was opened on the Veridex computer.':'VLC did not launch.');}catch(e){notice(e.message);}
      };q('[data-file-actions]').append(vlc);
    }
  }
  function gallery(){
    const search=q('[data-search]').value.toLowerCase(),filter=q('[data-filter]').value;
    const matches=rows.filter(file=>(file.name||'').toLowerCase().includes(search)&&(filter==='all'||filter==='export'&&file.source==='generated'||filter==='document'&&!['video','audio','image'].includes(type(file))||type(file)===filter));
    q('[data-count]').textContent=`${matches.length} files${loading?' · Loading…':''}`;
    const grid=q('[data-gallery]');grid.replaceChildren();grid.classList.toggle('is-list',listView);
    for(const file of matches.slice(0,limit)){
      const button=document.createElement('button');button.type='button';button.className='video-media-tile';button.setAttribute('aria-pressed',String(selected===file.file_id));
      if(type(file)==='image'){const img=document.createElement('img');img.loading='lazy';img.alt='';img.src=url(file);button.append(img);}
      else{const badge=document.createElement('span');badge.className='video-media-kind';badge.textContent=type(file)==='video'?'▶ VIDEO':type(file)==='audio'?'♫ AUDIO':'FILE';button.append(badge);}
      const name=document.createElement('strong');name.textContent=file.name;const size=document.createElement('small');size.textContent=formatBytes(file.size||0);button.append(name,size);
      button.onclick=()=>{selected=file.file_id;notice('');gallery();preview();};grid.append(button);
    }
    if(!matches.length){const empty=document.createElement('p');empty.textContent=rows.length?'No matching files.':'No room media yet. Use Add files in the top toolbar.';grid.append(empty);}
    q('[data-more]').hidden=matches.length<=limit;
  }
  async function refresh(){
    if(!current())return;const expected=scope,version=++generation;loading=1;gallery();
    try{const response=await api(`/api/room/files?${new URLSearchParams({workspace_id:state.workspace.workspace_id,room_id:'video_production'})}`);
      if(!current()||expected!==scope||version!==generation)return;rows=response.files||[];if(!rows.some(file=>file.file_id===selected)){selected='';preview();}
    }catch(e){if(current()&&expected===scope)notice(e.message);}finally{if(current()&&version===generation){loading=0;gallery();}}
  }
  q('[data-search]').oninput=gallery;q('[data-filter]').onchange=()=>{limit=60;gallery();};q('[data-more]').onclick=()=>{limit+=60;gallery();};q('[data-refresh]').onclick=refresh;
  q('[data-view]').onclick=()=>{listView=!listView;q('[data-view]').textContent=listView?'Gallery view':'List view';q('[data-view]').setAttribute('aria-pressed',String(listView));gallery();};
  q('[data-hide-gallery]').onclick=()=>{workspace.classList.toggle('gallery-hidden');q('[data-hide-gallery]').textContent=workspace.classList.contains('gallery-hidden')?'Show gallery':'Hide gallery';};
  async function upload(files){
    if(!current()||request)return;const original=scope,parameters=context();q('[data-cancel-upload]').hidden=false;
    try{
      for(const file of files){
        if(!current()||scope!==original)break;
        await new Promise((resolve,reject)=>{
          const xhr=new XMLHttpRequest();request=xhr;xhr.open('POST',`/api/video/upload?${new URLSearchParams({...parameters,name:file.name})}`);xhr.setRequestHeader('Content-Type',file.type||'application/octet-stream');
          xhr.upload.onprogress=event=>{if(current())notice(`Uploading ${file.name}: ${event.lengthComputable?Math.round(event.loaded/event.total*100)+'%':formatBytes(event.loaded)}`);};
          xhr.onload=()=>{let result;try{result=JSON.parse(xhr.responseText);}catch{reject(new Error('Invalid upload response'));return;}if(xhr.status>=200&&xhr.status<300)resolve(result);else reject(new Error(result.error||'Upload failed'));};
          xhr.onerror=()=>reject(new Error('Upload failed; check the connection'));xhr.onabort=()=>reject(new Error('Upload stopped'));xhr.send(file);
        });request=null;
      }
      if(current()&&scope===original){notice('Room files imported. Nothing was sent to chat.');await refresh();}
    }catch(e){if(current()&&scope===original)notice(e.message);}finally{request=null;q('[data-room-upload]').value='';q('[data-cancel-upload]').hidden=true;}
  }
  window.videoRoomAddFiles=()=>{if(current())q('[data-room-upload]').click();};q('[data-room-upload]').onchange=event=>upload([...event.target.files]);
  q('[data-cancel-upload]').onclick=()=>request?.abort();
  workspace.addEventListener('dragover',event=>{event.preventDefault();event.stopPropagation();});
  workspace.addEventListener('drop',event=>{event.preventDefault();event.stopPropagation();upload([...event.dataTransfer.files]);});
  document.getElementById('toolbar-view-files').addEventListener('click',event=>{if(current()){event.stopImmediatePropagation();q('[data-search]').focus();}},true);
  window.renderVideoRoom=()=>{
    const enabled=state.session?.active_room==='video_production';
    if(enabled){
      if(!active){active=true;workspace.hidden=false;main.classList.add('video-production-active');q('[data-actions]').append(actions);chat.append(messages,composer);attach.hidden=false;}
      if(scope!==key()){if(request)request.abort();scope=key();rows=[];selected='';closeChat();preview();refresh();}
    }else if(active){
      active=false;scope='';generation++;loading=0;if(request)request.abort();workspace.hidden=true;chat.hidden=true;main.classList.remove('video-production-active');main.append(messages,composer);composer.prepend(actions);attach.hidden=true;preview();
    }
  };
  window.renderVideoRoom();
})();
