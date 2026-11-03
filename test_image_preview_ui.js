'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
class Element {
  constructor(tag='div') {this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.value='';this.textContent='';this.attributes={};this.open=false;}
  append(...items){this.children.push(...items);}
  addEventListener(type,fn){(this.listeners[type]||=[]).push(fn);}
  setAttribute(key,value){this.attributes[key]=value;}
  querySelector(tag){return flatten(this).find(element=>element!==this&&element.tagName===tag.toUpperCase())||null;}
  get options(){return this.children.filter(child=>child.tagName==='OPTION');}
  get selectedOptions(){return this.options.filter(option=>String(option.value)===String(this.value));}
  showModal(){this.open=true;}
  close(){this.open=false;}
  remove(){this.removed=true;}
  focus(){}
}
function flatten(element){return [element,...element.children.flatMap(flatten)];}
function button(element,label){const found=flatten(element).find(row=>row.tagName==='BUTTON'&&row.textContent===label);assert.ok(found,'Missing button '+label);return found;}
async function fire(element,type='click'){
  if(element.disabled)return;
  for(const listener of element.listeners[type]||[])await listener({preventDefault(){},target:element});
  await flush();
}
function harness(){
  const body=new Element('body'),elements=new Map(),calls=[],notices=[],previews=[];
  const state={workspace:{workspace_id:'ws_one',label:'One'},session:{session_id:'sess_one',active_room:'art_department'},workspaces:[{workspace_id:'ws_one',label:'One'},{workspace_id:'ws_two',label:'Two'}],rooms:[{id:'lobby',title:'Lobby'},{id:'art_department',title:'Visual Design'},{id:'control_room',title:'Control Room'}],files:[],artImages:[],roomFiles:[],selectedFiles:new Set()};
  const context=vm.createContext({state,console,crypto:require('node:crypto'),window:{addEventListener(){}},
    document:{body,createElement:tag=>new Element(tag),getElementById:id=>{if(!elements.has(id))elements.set(id,new Element('dialog'));return elements.get(id);}},
    URL:{createObjectURL:()=> 'blob:edited',revokeObjectURL(){}},
    showToast:value=>notices.push(value),artImageContentUrl:file=>'/image/'+file.file_id,
    renderFiles(){},renderArtGallery(){},renderRoomFileLibrary(){},
    fetch:async(path,options)=>{previews.push(JSON.parse(options.body));return {ok:true,blob:async()=>({})};},
    api:async(path,options)=>{
      const payload=JSON.parse(options.body);calls.push({path,payload});
      if(path.endsWith('/send')&&context.failSend){context.failSend=false;throw new Error('fixture send failed');}
      return {file:{file_id:'file_saved',name:'item--edited.png',content_type:'image/png',sha256:'saved-hash'}};
    }
  });
  vm.runInContext(fs.readFileSync('web/image_preview.js','utf8'),context);
  function mount(name='file_source'){
    const file={file_id:name,name:'item.png',sha256:'original-hash',content_type:'image/png'};state.files=[file];
    const hero=new Element('figure');hero.append(new Element('img'));
    const actions=new Element('div');const original=new Element('a');original.textContent='Open original';actions.append(original);
    context.window.ImagePreviewTools.mount(file,'session',hero,actions);
    return {hero,actions,file};
  }
  const latestDialog=()=>body.children.filter(child=>child.tagName==='DIALOG'&&!child.removed).at(-1);
  return {context,state,calls,notices,previews,mount,latestDialog,tools:context.window.ImagePreviewTools};
}
(async()=>{
  {
    const h=harness(),view=h.mount();
    await fire(button(view.actions,'Touch up'));
    assert.equal(h.previews.length,1);assert.equal(h.calls.length,0,'Touch up must not persist');
    assert.equal(view.hero.querySelector('img').src,'blob:edited');
    await fire(button(view.actions,'Revert'));
    assert.equal(view.hero.querySelector('img').src,'/image/file_source');
    assert.equal(h.calls.length,0);
    await fire(button(view.actions,'Touch up'));await fire(button(view.actions,'Save copy'));
    assert.equal(h.calls.length,1);assert.equal(h.calls[0].payload.confirm,true);
    assert.equal(h.state.selectedSessionFileId,'file_saved');
  }
  {
    const h=harness(),view=h.mount();await fire(button(view.actions,'Touch up'));
    let pending=h.tools.leave('session');await flush();await fire(button(h.latestDialog(),'Keep editing'));
    assert.equal(await pending,false);assert.equal(h.calls.length,0);
    pending=h.tools.leave('session');await flush();await fire(button(h.latestDialog(),'Discard'));
    assert.equal(await pending,true);assert.equal(view.hero.querySelector('img').src,'/image/file_source');
    await fire(button(view.actions,'Touch up'));
    pending=h.tools.leave('session');await flush();await fire(button(h.latestDialog(),'Save copy'));
    assert.equal(await pending,true);assert.equal(h.calls.length,1);
  }
  {
    const h=harness(),view=h.mount();await fire(button(view.actions,'Edit'));
    const editor=h.latestDialog(),brightness=flatten(editor).find(row=>row.attributes['aria-label']==='brightness');
    brightness.value=15;await fire(brightness,'input');
    await fire(button(editor,'Save copy'));
    assert.equal(h.previews.at(-1).recipe.adjustments.brightness,15,'Save includes unapplied control changes');
    assert.equal(h.calls[0].payload.recipe.adjustments.brightness,15);
    assert.equal(brightness.value,0,'saved edits reset editor controls to new source');
  }
  {
    const h=harness(),view=h.mount();await fire(button(view.actions,'Touch up'));await fire(button(view.actions,'Send'));
    const dialog=h.latestDialog(),selects=flatten(dialog).filter(row=>row.tagName==='SELECT');
    assert.equal(selects[0].value,'ws_one','current workspace is the default');
    assert.ok(selects[1].options.every(option=>option.value!=='lobby'));
    selects[0].value='ws_two';selects[1].value='control_room';h.context.failSend=true;
    await fire(button(dialog,'Save copy and send'));
    assert.equal(h.calls[0].path,'/api/room/images/save');assert.equal(h.calls[1].path,'/api/room/images/send');
    assert.equal(dialog.open,true,'failed send stays open for retry');
    const requestId=h.calls[1].payload.request_id;
    await fire(button(dialog,'Send'));
    assert.equal(h.calls.filter(row=>row.path.endsWith('/save')).length,1,'retry must not save a second edited copy');
    assert.equal(h.calls.at(-1).payload.request_id,requestId);
    assert.equal(h.calls.at(-1).payload.target_workspace_id,'ws_two');
    assert.equal(h.state.workspace.workspace_id,'ws_one');assert.equal(h.state.session.active_room,'art_department');
  }
  {
    const h=harness(),view=h.mount();let resolve;
    h.context.fetch=()=>new Promise(done=>resolve=()=>done({ok:true,blob:async()=>({})}));
    const pending=fire(button(view.actions,'Touch up'));await flush();
    assert.equal(await h.tools.leave('session'),false,'cannot abandon an in-flight preview');
    resolve();await pending;
  }
  {
    const h=harness(),view=h.mount();
    await fire(button(view.actions,'Remove background'));
    assert.equal(h.previews.at(-1).recipe.remove_background,true);
    assert.equal(h.calls.length,0,'background removal must be an unsaved preview');
    assert.equal(view.hero.querySelector('img').attributes['data-background-removed'],'true');
    await fire(button(view.actions,'Restore background'));
    assert.equal(view.hero.querySelector('img').src,'/image/file_source');
    await fire(button(view.actions,'Touch up'));
    await fire(button(view.actions,'Remove background'));
    await fire(button(view.actions,'Restore background'));
    assert.equal(h.previews.at(-1).recipe.auto,true,'restoring background keeps other adjustments');
    assert.equal(h.previews.at(-1).recipe.remove_background,false);
    await fire(button(view.actions,'Remove background'));
    await fire(button(view.actions,'Save copy'));
    assert.equal(h.calls[0].payload.recipe.remove_background,true);
  }
  console.log('6 image-preview UI interaction scenarios passed (DOM fixtures; not browser visual QA).');
})().catch(error=>{console.error(error);process.exitCode=1;});
