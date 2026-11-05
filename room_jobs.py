"""Durable room requests, immutable attempts, and independent production jobs."""
import copy
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from veridex_core import utc_now

ACTIVE = {'submitting', 'queued', 'running', 'cancel_requested'}
IMAGE_REQUEST = re.compile(r'\b(make|create|generate|draw|design|render)\b[\s\S]{0,140}\b(image|picture|photo|illustration|artwork|meme|poster|logo|icon|png|jpe?g|webp)s?\b', re.I)
IMAGE_EDIT = re.compile(r'\b(touch\s*up|retouch|edit|enhance|restore|repair|straighten|crop|remove|replace|clean\s*up)\b',re.I)
IMAGE_SUBJECT = re.compile(r'\b(image|picture|photo|poster|frame|artwork|png|jpe?g|webp)s?\b',re.I)


def image_operation(prompt, has_image=False):
    if IMAGE_EDIT.search(prompt) and (has_image or IMAGE_SUBJECT.search(prompt)):
        return 'edit'
    return 'generate' if IMAGE_REQUEST.search(prompt) else ''


def precreation_questions(prompt):
    questions=[]
    if not re.search(r'\b(meme|poster|logo|icon|website|print|social|instagram|youtube|for)\b',prompt,re.I):
        questions.append('Where will you use the image?')
    if not re.search(r'\b(realistic|photograph|cartoon|comic|sketch|watercolor|minimal|style|meme)\b',prompt,re.I):
        questions.append('Do you have a preferred visual style?')
    if re.search(r'\b(meme|caption|text|words)\b',prompt,re.I) and not re.search(r'["“].+?["”]',prompt) and not re.search(r'\b(no|without)\s+(text|caption|words)\b',prompt,re.I):
        questions.append('What exact text, if any, should appear?')
    return questions


class RoomJobs:
    def __init__(self, store, renderer, validator):
        self.store, self.renderer, self.validator = store, renderer, validator
        self.lock = store._lock
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='room-production')
        self.events, self.futures, self.recovered = {}, {}, set()
        self.external_cancel = None

    def _defaults(self,row):
        row.setdefault('origin','chat')
        row.setdefault('project_id','')
        row.setdefault('destination_room',row['room_id'])
        row.setdefault('task_kind','image')
        # Legacy requests were already visible before explicit draft saving existed.
        # New unsaved drafts carry listed=False at creation; preserve that choice.
        row.setdefault('listed',True)
        row.setdefault('workspace_visible',row.get('status') not in {'draft','completed'})
        row.setdefault('progress',0)
        row['brief'].setdefault('output_name',f"image-{row['number']:06d}")
        return row

    def _folder(self, ws):
        self.store.get_workspace(ws)
        return self.store.workspace_dir(ws) / 'room_jobs'

    def _path(self, ws, request_id):
        if not re.fullmatch(r'rj_[a-f0-9]{32}', str(request_id)):
            raise ValueError('Invalid room request ID')
        return self._folder(ws) / (request_id + '.json')

    def _save(self, row, event):
        row['updated_at'] = utc_now()
        folder = self._folder(row['workspace_id']); folder.mkdir(parents=True, exist_ok=True)
        audit = {'event':event,'request_id':row['request_id'],'version':row['version'],'status':row['status'],'at':row['updated_at']}
        with (folder / 'events.ndjson').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(audit) + '\n')
        self.store._write_json(self._path(row['workspace_id'], row['request_id']), row)

    def _notice(self, row):
        key = f"{row['request_id']}:{len(row['attempts'])}:{row['status']}"
        with self.lock:
            existing = self.store.load_messages(row['workspace_id'], row['session_id'])
            if any(message.get('job_notice_key') == key for message in existing):
                return
            text = f"Request #{row['number']:06d}: {row['status'].replace('_', ' ')}."
            if row['status'] == 'completed':
                text += ' Your result is ready in the room job list.'
            elif row['status'] in {'failed', 'interrupted'}:
                text += ' Open the job details, or ask Systems about this request.'
            elif row['status'] == 'draft':
                text += ' Your brief is saved in Jobs.'
            self.store.append_message(row['workspace_id'], row['session_id'], 'assistant', text,
                room=row['room_id'], speaker=row['persona'], model='deterministic',
                reasoning_effort='none', task_type='room_job_notice',
                room_job_id=row['request_id'], job_notice_key=key)

    def _recover(self, ws):
        if ws in self.recovered:
            return
        for path in self._folder(ws).glob('rj_*.json'):
            row = self.store._read_json(path, {})
            if row.get('status') in ACTIVE:
                row['status'] = 'interrupted'; row['error'] = 'Backend restarted before execution finished. Retry explicitly.'
                row['save_draft_pending']=False
                if row['attempts']: row['attempts'][-1].update(status='interrupted', finished_at=utc_now())
                row['version'] += 1; self._save(row, 'interrupted'); self._notice(row)
            elif row.get('status') in {'completed','failed','canceled','interrupted'}:
                self._notice(row)
        self.recovered.add(ws)

    def get(self, ws, room, request_id):
        with self.lock:
            self._recover(ws)
            row = self.store._read_json(self._path(ws, request_id), {})
            if not row or row.get('workspace_id') != ws or row.get('room_id') != room:
                raise ValueError('Request is unavailable in this workspace and room')
            return copy.deepcopy(self._defaults(row))

    def list(self, ws, room):
        with self.lock:
            self._recover(ws)
            rows = [self.store._read_json(path,{}) for path in self._folder(ws).glob('rj_*.json')]
            return sorted([self._defaults(row) for row in rows if row.get('room_id') == room], key=lambda row:row['number'], reverse=True)

    def create(self, ws, session, room, persona, prompt, source_ids=None, parent_id='', operation='generate', client_id='', project_id='', destination_room='', task_kind='image', dispatch_context=None):
        if room != 'art_department' and not (room=='estate_sales_room' and project_id and destination_room):
            raise ValueError('Image production requests currently belong in Visual Design')
        prompt = str(prompt).strip()
        if not prompt or len(prompt) > 12000:
            raise ValueError('Provide an image brief of at most 12000 characters')
        with self.lock:
            owner = self.store.find_session(session)
            if owner.get('workspace_id') != ws: raise ValueError('Session does not belong to workspace')
            self._recover(ws)
            if client_id:
                duplicate = next((row for row in self.list(ws,room) if row.get('client_id') == client_id and row['session_id'] == session), None)
                if duplicate: return duplicate
            parent = self.get(ws, room, parent_id) if parent_id else None
            counter = self.store.root / 'room_job_sequence.json'
            number = int(self.store._read_json(counter, {}).get('number',0)) + 1
            self.store._write_json(counter, {'number':number})
            row = dict(request_id='rj_' + uuid.uuid4().hex, number=number, workspace_id=ws,
                session_id=session, room_id=room, persona=persona, client_id=client_id,
                parent_request_id=parent_id, status='draft', version=1, title=prompt[:90],
                original_instructions=prompt, answers=[], created_at=utc_now(), attempts=[], files=[], error='', accepted=False,
                origin='chat',listed=False,workspace_visible=False,progress=0,
                project_id=project_id,destination_room=destination_room or room,task_kind=task_kind,dispatch_context=copy.deepcopy(dispatch_context or {}),
                brief=dict(prompt=prompt, source_file_ids=list(source_ids or []), operation=operation,
                    aspect='square', variants=1, options={}, assumptions='One square PNG; preserve supplied source images.'))
            if re.search(r'\blandscape\b',prompt,re.I): row['brief']['aspect']='landscape'
            elif re.search(r'\bportrait\b',prompt,re.I): row['brief']['aspect']='portrait'
            row['brief']['assumptions']=f"One {row['brief']['aspect']} PNG; preserve supplied source images."
            if parent:
                row['brief']['source_file_ids'] = [file['file_id'] for file in parent['files']][:4]
                row['brief']['aspect'] = parent['brief']['aspect']
            row['brief']['output_name']=f'{"image" if task_kind=="image" else task_kind}-{number:06d}'
            self._save(row,'draft_created'); return copy.deepcopy(row)

    def update(self, ws, room, request_id, version, brief):
        with self.lock:
            row = self.get(ws,room,request_id)
            if row['status'] != 'draft' or row['version'] != version:
                raise ValueError('Draft changed or was submitted; reopen its latest version')
            updated = {**row['brief'], **{key:value for key,value in brief.items() if key in row['brief']}}
            if not str(updated['prompt']).strip() or len(str(updated['prompt'])) > 12000:
                raise ValueError('Provide an image brief of at most 12000 characters')
            valid_aspect=updated['aspect'] in {'square','landscape','portrait'} or (row.get('origin')=='art_studio' and updated['aspect']==row['brief']['aspect'])
            if not valid_aspect or int(updated['variants']) not in range(1,5):
                raise ValueError('Choose a supported aspect and 1 to 4 variants')
            if updated['operation'] not in {'generate','edit','resize','convert'}:
                if row.get('origin')!='art_studio' or updated['operation']!=row['brief']['operation']:
                    raise ValueError('Unsupported image operation')
            from image_names import image_name
            image_name(updated.get('output_name',''))
            if not isinstance(updated['options'],dict): raise ValueError('Invalid output options')
            if updated['options'].get('format','PNG') not in {'PNG','JPEG','WEBP'}: raise ValueError('Unsupported image format')
            for dimension in ('width','height'):
                if updated['options'].get(dimension) is not None and int(updated['options'][dimension]) not in range(64,5001):
                    raise ValueError('Image dimensions must be between 64 and 5000 pixels')
            row['brief'] = updated; row['version'] += 1; row['error'] = ''
            row['answers'].append(copy.deepcopy(updated)); self._save(row,'draft_updated'); return copy.deepcopy(row)

    def submit(self, ws, room, request_id, version, confirm=False, retry=False):
        with self.lock:
            row = self.get(ws,room,request_id)
            if confirm is not True: raise ValueError('Choose Send to room to submit this brief')
            if not retry and row['status'] != 'draft': return row
            if row['version'] != version: raise ValueError('The brief changed; review its latest version before sending')
            if retry and row['status'] not in {'failed','canceled','interrupted'}:
                raise ValueError('Only a stopped or failed request can be retried')
            row['status']='submitting';row['listed']=True;row['workspace_visible']=True
            event=threading.Event();self.events[request_id]=event
            self._save(row,'submission_started')
        # Planning/provider readiness checks must never hold the shared store lock.
        try:
            review_input=copy.deepcopy(row)
            review_input['_cancel_event']=event
            review=self.validator(review_input) or {}
            if review.get('approved') is False: raise ValueError('Production review needs clarification')
        except Exception as exc:
            with self.lock:
                row=self.get(ws,room,request_id);row['status']='canceled' if event.is_set() else 'draft'
                if row.get('save_draft_pending'):
                    row.update(status='draft',workspace_visible=False,save_draft_pending=False)
                row['review']=locals().get('review',{})
                row['error']='The room did not accept the request. Check its references, access, and image-tool availability.'
                row['diagnostic']={'stage':'submission','error_code':type(exc).__name__,'request_id':request_id}
                if row['review'].get('questions'):
                    row['error']='Continue pre-creation: '+'; '.join(str(value)[:300] for value in row['review']['questions'][:5])
                self._save(row,'submission_rejected')
                self.store.append_message(ws,row['session_id'],'assistant',f"Request #{row['number']:06d}: {row['error']}",room=room,speaker=row['persona'],room_job_id=request_id)
            raise ValueError(row['error']) from exc
        with self.lock:
            row=self.get(ws,room,request_id);row['review']=review
            if event.is_set():
                row['status']='draft' if row.pop('save_draft_pending',False) else 'canceled'
                if row['status']=='draft':row['workspace_visible']=False
                self._save(row,'canceled');self._notice(row);return row
            row['status']='queued';row['error']='';row['version']+=1
            attempt=dict(attempt_id='attempt_'+uuid.uuid4().hex,status='queued',brief=copy.deepcopy(row['brief']),submitted_at=utc_now())
            row['attempts'].append(attempt);self._save(row,'accepted')
            self.store.append_message(ws,row['session_id'],'assistant',f"Request #{row['number']:06d} was received by the room and is queued. You can continue chatting.",room=room,speaker=row['persona'],room_job_id=request_id,task_type='room_job_accepted')
            self.futures[request_id]=self.pool.submit(self._run,ws,room,request_id,event)
            return copy.deepcopy(row)

    def _run(self, ws,room,request_id,event):
        with self.lock:
            row = self.get(ws,room,request_id)
            row['status'] = 'running'; row['attempts'][-1]['status'] = 'running'; self._save(row,'started')
        try:
            if event.is_set(): raise InterruptedError()
            result = self.renderer(copy.deepcopy(row),event)
            with self.lock:
                row = self.get(ws,room,request_id)
                row['files'] = result.get('files',[])
                row['production_route'] = result.get('route',{})
                if not event.is_set() and not row['files']: raise ValueError('No verified output')
                row['status'] = 'canceled' if event.is_set() else 'completed'
        except Exception as exc:
            with self.lock:
                row = self.get(ws,room,request_id)
                row['status'] = 'canceled' if event.is_set() else 'failed'
                row['error'] = '' if event.is_set() else f"Production failed ({type(exc).__name__}). No completed result was verified."
                row['diagnostic']={'stage':'production','error_code':type(exc).__name__,'request_id':request_id}
        with self.lock:
            pending=self.get(ws,room,request_id).get('save_draft_pending',False)
            if event.is_set():
                row['status']='canceled'; row['error']=''
            row['attempts'][-1].update(status=row['status'],finished_at=utc_now(),error=row['error'],files=row['files'],route=row.get('production_route',{}))
            if pending and event.is_set():row.update(status='draft',workspace_visible=False,save_draft_pending=False)
            if row['status']=='completed':row.update(workspace_visible=False,progress=100)
            row['version'] += 1; self._save(row,row['status']); self._notice(row)

    def cancel(self, ws,room,request_id):
        external=None
        with self.lock:
            row = self.get(ws,room,request_id)
            if row['status'] in ACTIVE:
                row['status'] = 'cancel_requested'; self._save(row,'cancel_requested')
                if row.get('origin')=='art_studio':external=row
                else:self.events[request_id].set()
        if external and self.external_cancel:self.external_cancel(external)
        return self.get(ws,room,request_id)

    def save_draft(self,ws,room,request_id):
        with self.lock:
            row=self.get(ws,room,request_id)
            if row['status']=='completed':raise ValueError('This job already completed. Open its result or create a revision.')
            row['listed']=True
            if row['status'] in ACTIVE:
                row['save_draft_pending']=True;self._save(row,'save_draft_requested')
            else:
                row.update(status='draft',workspace_visible=False,error='',save_draft_pending=False)
                row['version']+=1;self._save(row,'draft_saved');return copy.deepcopy(row)
        return self.cancel(ws,room,request_id)

    def track_art_job(self,ws,session,persona,payload,job,request_id=''):
        with self.lock:
            row=self.get(ws,'art_department',request_id) if request_id else next((r for r in self.list(ws,'art_department') if r.get('external_job_id')==job['job_id']),None)
            if not row:
                row=self.create(ws,session,'art_department',persona,payload.get('prompt') or f"Art Studio {payload.get('operation','image')}",payload.get('source_file_ids'),operation=payload.get('operation','generate'),client_id='studio:'+job['job_id'])
            if row.get('external_job_id')!=job['job_id']:
                if job['status']!='queued':return row
                row['attempts'].append(dict(attempt_id=job['job_id'],status='queued',brief=copy.deepcopy(row['brief']),submitted_at=job['created_at']))
            row.update(origin='art_studio',external_job_id=job['job_id'],studio_payload=copy.deepcopy(payload),listed=True)
            row['brief'].update({k:payload[k] for k in ('prompt','source_file_ids','aspect','variants','options','output_name') if k in payload})
            row['status']='cancel_requested' if job['status']=='canceling' else job['status']
            row['progress']=job.get('progress',0)
            row['workspace_visible']=row['status']!='completed'
            row['error']='Art Studio production failed. Ask Systems about this job.' if row['status']=='failed' else ''
            if row['status']=='failed':row['diagnostic']={'stage':'art_studio','error_code':job.get('error_type','ProductionError')}
            if row['status']=='completed':
                row['files']=job.get('result',{}).get('files',[])
                if not row['files']:raise ValueError('No verified Art Studio output')
                row['production_route']={k:row['files'][0].get(k,'local') for k in ('provider','model')}
            attempt=row['attempts'][-1]
            attempt.update(status=row['status'],route=row.get('production_route',{}))
            if row['status'] in {'completed','failed','canceled'}:
                attempt.update(finished_at=utc_now(),files=copy.deepcopy(row.get('files',[])),error=row['error'])
                if row['status']=='canceled' and row.pop('save_draft_pending',False):row.update(status='draft',workspace_visible=False)
            row['version']+=1;self._save(row,'art_studio_'+job['status'])
            if row['status'] in {'completed','failed','canceled','draft'}:self._notice(row)
            return copy.deepcopy(row)

    def import_art_images(self,ws,images):
        with self.lock:
            known=self.list(ws,'art_department')
            known_files={f['file_id'] for r in known for f in r.get('files',[])}
            known_native={r.get('external_job_id') for r in known}
            groups={}
            for file in images:
                # Room-library copies have no producing session or generation job.
                if not file.get('source_session_id'):continue
                if file['file_id'] in known_files:continue
                native=str(file.get('metadata',{}).get('art',{}).get('job_id') or '')
                if native.startswith('rj_') or (native and native in known_native):continue
                groups.setdefault(native or file['file_id'],[]).append(file)
            for native,files in groups.items():
                session=files[0]['source_session_id']
                row=self.create(ws,session,'art_department','Creative Director',files[0].get('display_name') or files[0]['name'],client_id='import:'+native)
                row.update(origin='art_studio',history_kind='imported_result',external_job_id=native,status='completed',files=files,listed=True,workspace_visible=False,created_at=files[0].get('created_at') or row['created_at'])
                self._save(row,'art_studio_result_imported')

    def accept(self, ws,room,request_id):
        with self.lock:
            row=self.get(ws,room,request_id)
            if row['status'] != 'completed': raise ValueError('Only completed images can be accepted')
            row['accepted']=True; self._save(row,'result_accepted'); return copy.deepcopy(row)
