(() => {
  const panel = document.createElement('dialog');
  panel.className = 'video-tools-dialog';
  panel.innerHTML = `<header><h2>Production tools</h2><button type="button" data-close aria-label="Close production tools">Close</button></header>
    <p>Applications run on the Veridex computer. Select a room file or open an application without a file.</p>
    <label>Room file <select data-source><option value="">No file selected</option></select></label>
    <button type="button" data-refresh>Refresh status</button> <button type="button" data-import>Import saved result</button>
    <input type="file" data-upload hidden><section data-apps></section>
    <details><summary>OBS recording controls</summary><p>In OBS: Tools → WebSocket Server Settings → enable the server and authentication. Keep the password here only; it is not saved.</p>
    <label>OBS password <input type="password" data-password autocomplete="off"></label>
    <label>Scene <input data-scene></label>
    <button data-obs="status">Recording status</button><button data-obs="scenes">List scenes</button><button data-obs="scene">Select scene</button><button data-obs="start">Start recording</button><button data-obs="stop">Stop recording</button></details>
    <details><summary>Audacity automation setup</summary><p>Enable mod-script-pipe in Audacity Preferences → Modules and restart Audacity. This enables local scripting access. Use an empty project for automated normalization; other editing remains in Audacity.</p><button data-audio-test>Test audio control</button></details>
    <pre data-message role="status"></pre><section data-jobs></section>`;
  document.body.append(panel);
  const q = s => panel.querySelector(s);
  let scope, timer;
  const call = async (action, extra = {}) => {
    if (!scope || state.session?.session_id !== scope.session_id || state.session?.active_room !== 'video_production') throw new Error('Return to the original Video Production session');
    return api('/api/video/action', {method: 'POST', body: JSON.stringify({...scope, action, ...extra})});
  };
  const message = value => { q('[data-message]').textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2); };
  async function refresh() {
    try {
      const result = await call('status');
      q('[data-apps]').replaceChildren();
      for (const [tool, info] of Object.entries(result.tools)) {
        if (['ffmpeg', 'ffprobe'].includes(tool)) continue;
        const row = document.createElement('div');
        const label = document.createElement('strong'); label.textContent = `${info.name}: ${info.state} · ${info.automation_state}`; row.append(label);
        const actions = [...info.actions]; if (tool === 'audacity' && info.available) actions.push('normalize');
        for (const action of actions) {
          const button = document.createElement('button'); button.type = 'button';
          button.textContent = action === 'open' ? 'Open' : action === 'normalize' ? 'Normalize audio copy' : action === 'convert' ? 'Convert / compress' : 'Render MLT project';
          button.onclick = async () => {
            if (!window.confirm(`${button.textContent} using ${info.name} on the Veridex computer?`)) return;
            try { message(await call(action === 'open' ? 'open' : 'job', {tool, file_id: q('[data-source]').value, confirm: true})); await refresh(); }
            catch(e) {message(e.message);}
          }; row.append(button);
        }
        if (info.setup) {const note = document.createElement('p');note.textContent = info.setup;row.append(note);}
        q('[data-apps]').append(row);
      }
      q('[data-jobs]').replaceChildren();
      for (const job of result.jobs || []) {
        const row = document.createElement('div');row.textContent = `${job.tool}: ${job.status} · ${job.elapsed_seconds}s ${job.error || ''}`;
        if (['queued','running'].includes(job.status)) {
          const stop = document.createElement('button');stop.textContent='Cancel';stop.onclick=async()=>{try{message(await call('cancel',{job_id:job.job_id,confirm:true}));}catch(e){message(e.message);}};row.append(stop);
        }
        q('[data-jobs]').append(row);
      }
    } catch(e) {message(e.message);}
  }
  document.getElementById('video-tools-open').onclick = async () => {
    scope = {workspace_id:state.workspace.workspace_id,session_id:state.session.session_id};
    await loadRoomFiles();q('[data-source]').replaceChildren(new Option('No file selected',''));
    for(const file of state.roomFiles) q('[data-source]').add(new Option(file.name,file.file_id));
    panel.showModal();await refresh();clearInterval(timer);timer=setInterval(refresh,3000);
  };
  q('[data-close]').onclick=()=>panel.close();
  panel.addEventListener('close',()=>{clearInterval(timer);q('[data-password]').value='';});
  q('[data-refresh]').onclick=refresh;
  q('[data-import]').onclick=()=>q('[data-upload]').click();
  q('[data-upload]').onchange=async e=>{
    try {
      for(const file of e.target.files) await api(`/api/files?${new URLSearchParams({...scope,name:file.name})}`,{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});
      await loadRoomFiles();message('Result uploaded and registered in this room. Reopen the panel to select it.');
    }catch(error){message(error.message);}finally{e.target.value='';}
  };
  for(const button of panel.querySelectorAll('[data-obs]'))button.onclick=async()=>{
    const operation=button.dataset.obs;
    if(!['status','scenes'].includes(operation)&&!window.confirm(`${button.textContent} in OBS?`))return;
    try{message(await call('obs_'+operation,{password:q('[data-password]').value,scene:q('[data-scene]').value,confirm:true}));}catch(e){message(e.message);}
  };
  q('[data-audio-test]').onclick=async()=>{try{message(await call('audio_test',{confirm:true}));}catch(e){message(e.message);}};
})();
