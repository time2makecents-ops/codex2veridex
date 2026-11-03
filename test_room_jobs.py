import tempfile
import io
import hashlib
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from room_jobs import RoomJobs, precreation_questions
from veridex_core import VeridexStore
from PIL import Image
from art_studio import ArtJobManager
from image_names import image_name
import veridex_server as server


class RoomJobTests(unittest.TestCase):
    def image_bytes(self):
        stream=io.BytesIO();Image.new('RGB',(8,8),'green').save(stream,'PNG');return stream.getvalue()

    def test_touchup_and_bare_send_prepare_the_attached_edit_without_execution(self):
        attached=self.store.save_file(self.ws,self.session,'source.png',self.image_bytes(),'image/png')
        with patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager),patch.object(server,'invoke_codex') as invoke:
            result=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':'Touch up the attached artwork','attachment_ids':[attached['file_id']],'request_id':'edit_attached'})
            row=result['room_job'];self.assertEqual(row['brief']['operation'],'edit')
            self.assertEqual(row['brief']['source_file_ids'],[attached['file_id']])
            review=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':'**send','request_id':'confirm_edit'})
            self.assertEqual(review['room_job_confirmation']['request_id'],row['request_id'])
            self.assertEqual(review['room_job_confirmation']['references'][0]['file_id'],attached['file_id'])
            self.assertEqual(review['room_job']['attempts'],[]);invoke.assert_not_called()

    def test_recovery_uses_latest_untracked_edit_and_preserves_its_source(self):
        attached=self.store.save_file(self.ws,self.session,'reference.png',self.image_bytes(),'image/png')
        self.store.append_message(self.ws,self.session,'user','Create a PNG of a circle',request_id='old_image')
        self.store.append_message(self.ws,self.session,'user','Retouch this artwork',request_id='untracked_edit',attachments=[server.public_file(attached)])
        with patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager),patch.object(server,'invoke_codex') as invoke:
            result=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':'send','request_id':'recover_edit'})
        self.assertEqual(result['room_job']['brief']['operation'],'edit')
        self.assertEqual(result['room_job']['brief']['source_file_ids'],[attached['file_id']]);invoke.assert_not_called()

    def test_draft_visibility_save_cancel_resume_and_completion_archive(self):
        row=self.draft();self.assertFalse(row['listed']);self.assertFalse(row['workspace_visible'])
        self.manager.submit(self.ws,'art_department',row['request_id'],1,True);self.assertTrue(self.started.wait(2))
        running=self.manager.get(self.ws,'art_department',row['request_id']);self.assertTrue(running['listed']);self.assertTrue(running['workspace_visible'])
        stopping=self.manager.save_draft(self.ws,'art_department',row['request_id']);self.assertTrue(stopping['save_draft_pending']);self.assertTrue(stopping['workspace_visible'])
        self.release.set();self.manager.futures[row['request_id']].result(5)
        saved=self.manager.get(self.ws,'art_department',row['request_id']);self.assertEqual(saved['status'],'draft');self.assertFalse(saved['workspace_visible']);self.assertTrue(saved['listed']);self.assertEqual(saved['attempts'][0]['status'],'canceled')
        self.manager.submit(self.ws,'art_department',saved['request_id'],saved['version'],True);self.manager.futures[row['request_id']].result(5)
        completed=self.manager.get(self.ws,'art_department',row['request_id']);self.assertEqual(completed['status'],'completed');self.assertFalse(completed['workspace_visible']);self.assertEqual(len(completed['attempts']),2)

    def test_unlisted_drafts_are_excluded_from_history_until_saved(self):
        row=self.draft()
        with patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager):
            args={'workspace_id':self.ws,'session_id':self.session}
            result=server.room_job_action(args);self.assertEqual(result['jobs'],[]);self.assertEqual(result['current_draft']['request_id'],row['request_id'])
            server.room_job_action({**args,'action':'save_draft','room_job_id':row['request_id']})
            result=server.room_job_action(args);self.assertEqual(len(result['jobs']),1);self.assertEqual(result['workspace_jobs'],[])

    def test_legacy_drafts_remain_in_history_without_starting_production(self):
        legacy=self.draft()
        path=self.manager._path(self.ws,legacy['request_id'])
        stored=self.store._read_json(path,{})
        stored.pop('listed');stored.pop('workspace_visible')
        self.store._write_json(path,stored)
        unsaved=self.manager.create(self.ws,self.session,'art_department','Creative Director','Create an image of a circle')
        with patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager):
            result=server.room_job_action({'workspace_id':self.ws,'session_id':self.session})
        self.assertEqual([row['request_id'] for row in result['jobs']],[legacy['request_id']])
        self.assertEqual(result['jobs'][0]['status'],'draft')
        self.assertEqual(result['jobs'][0]['attempts'],[])
        self.assertEqual(result['workspace_jobs'],[])
        self.assertEqual(result['current_draft']['request_id'],unsaved['request_id'])
        self.assertFalse(self.manager.futures)
        self.assertNotIn('listed',self.store._read_json(path,{}))

    def test_rename_changes_labels_without_changing_original_or_ledger(self):
        content=self.image_bytes();file=self.store.save_file(self.ws,self.session,'original.png',content,'image/png',source='generated',kind='generated_image',scope='room',scope_ref='art_department')
        original_path=Path(file['path']);ledger=self.store.artifact_ledger_path(self.ws).read_bytes()
        renamed=self.store.rename_image(self.ws,self.session,file['file_id'],'Friendly image')
        self.assertEqual(renamed['display_name'],'Friendly image.png');self.assertEqual(renamed['path'],file['path'])
        self.assertEqual(original_path.read_bytes(),content);self.assertEqual(self.store.artifact_ledger_path(self.ws).read_bytes(),ledger)
        self.assertEqual(self.store.list_files(self.ws,self.session)[0]['display_name'],'Friendly image.png')
        self.assertEqual(self.store.list_generated_images(self.ws)[0]['display_name'],'Friendly image.png')
        with self.assertRaises(ValueError):self.store.rename_image(self.ws,self.session,file['file_id'],'../escape.png')
        original_path.write_bytes(b'tampered fixture')
        with self.assertRaises(ValueError):self.store.rename_image(self.ws,self.session,file['file_id'],'Changed')

    def test_image_names_validate_and_number_variants(self):
        self.assertEqual(image_name('Artwork.png','.png',index=2,count=3),'Artwork_02.png')
        for value in ('../file','CON','wrong:name','name\nheader'):
            with self.subTest(value=value),self.assertRaises(ValueError):image_name(value)

    def test_preview_delivery_is_inline_and_download_is_explicit(self):
        path=Path(self.temp.name)/'preview.png';path.write_bytes(self.image_bytes())
        for download in (False,True):
            headers={}
            handler=SimpleNamespace(headers={},send_response=lambda value:None,send_header=lambda key,value:headers.update({key:value}),end_headers=lambda:None,wfile=io.BytesIO())
            server.VeridexHandler._stream_media_file(handler,{'path':str(path),'content_type':'image/png','display_name':'Friendly image.png'},download)
            self.assertTrue(headers['Content-Disposition'].startswith('attachment' if download else 'inline'))
            self.assertIn('Friendly%20image.png',headers['Content-Disposition']);self.assertEqual(handler.wfile.getvalue(),path.read_bytes())

    def test_room_scoped_output_remains_in_origin_room_after_navigation(self):
        self.store.set_room(self.ws,self.session,'control_room')
        file=self.store.save_file(self.ws,self.session,'output.png',self.image_bytes(),'image/png',source='generated',kind='generated_image',scope='room',scope_ref='art_department')
        self.assertEqual(file['room_id'],'art_department');self.assertEqual(self.store.list_generated_images(self.ws)[0]['file_id'],file['file_id'])

    def test_art_studio_history_import_is_verified_and_idempotent(self):
        file=self.store.save_file(self.ws,self.session,'studio.png',self.image_bytes(),'image/png',source='generated',kind='generated_image',scope='room',scope_ref='art_department',metadata={'art':{'job_id':'artjob_fixture','provider':'fixture'}})
        with patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager):
            args={'workspace_id':self.ws,'session_id':self.session}
            first=server.room_job_action(args);second=server.room_job_action(args)
        row=first['jobs'][0];self.assertEqual(row['origin'],'art_studio');self.assertEqual(row['history_kind'],'imported_result')
        self.assertEqual(row['files'][0]['file_id'],file['file_id']);self.assertEqual(len(second['jobs']),1);self.assertEqual(first['workspace_jobs'],[])
        with patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager):
            restored=server.art_job_status('artjob_fixture',args)
        self.assertEqual(restored['status'],'completed');self.assertEqual(restored['result']['files'][0]['file_id'],file['file_id'])

    def test_art_studio_can_stop_save_and_resume_with_original_provider(self):
        native=ArtJobManager();started=threading.Event();release=threading.Event()
        def generate(payload,sources):
            started.set();release.wait(3)
            return [{'content':self.image_bytes(),'extension':'.png','content_type':'image/png','metadata':{'provider':'fixture','model':payload['model_id']}}]
        self.manager.external_cancel=lambda row:native.cancel(row['external_job_id'])
        try:
            with patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager),patch.object(server,'ART_JOBS',native),patch.object(server.ART,'generate',side_effect=generate) as generated:
                job=server.submit_art_job({'workspace_id':self.ws,'session_id':self.session,'prompt':'Create a fixture image','model_id':'explicit_fixture','output_name':'Named output'})
                self.assertTrue(started.wait(2));row=self.manager.list(self.ws,'art_department')[0]
                self.manager.save_draft(self.ws,'art_department',row['request_id']);release.set();native.wait(job['job_id'],5)
                draft=self.manager.get(self.ws,'art_department',row['request_id']);self.assertEqual(draft['status'],'draft');self.assertFalse(draft['workspace_visible'])
                server.room_job_action({'workspace_id':self.ws,'session_id':self.session,'action':'submit','room_job_id':draft['request_id'],'version':draft['version'],'confirm':True})
                resumed=self.manager.get(self.ws,'art_department',row['request_id']);native.wait(resumed['external_job_id'],5)
                final=self.manager.get(self.ws,'art_department',row['request_id']);self.assertEqual(final['status'],'completed');self.assertEqual(len(final['attempts']),2);self.assertFalse(final['workspace_visible'])
                self.assertEqual(final['files'][0]['name'],'Named output.png');self.assertEqual(generated.call_args.args[0]['model_id'],'explicit_fixture')
        finally:release.set();native._executor.shutdown(wait=True)

    def test_precreation_does_not_repeat_supplied_caption_decisions(self):
        self.assertFalse(any('exact text' in question for question in precreation_questions('Create a cartoon image. No text.')))
        self.assertFalse(any('exact text' in question for question in precreation_questions('Make a meme with text "example"')))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=VeridexStore(Path(self.temp.name))
        initial=self.store.ensure_default(); self.ws=initial['workspace']['workspace_id'];self.session=initial['session']['session_id']
        self.store.set_room(self.ws,self.session,'art_department')
        self.release=threading.Event();self.started=threading.Event();self.calls=[]
        def renderer(row,event):
            self.calls.append(row);self.started.set();self.release.wait(3)
            if event.is_set(): return {'files':[]}
            file=self.store.save_file(self.ws,self.session,'result.txt',b'verified fixture','text/plain',source='generated',scope='room',scope_ref='art_department')
            return {'files':[file],'route':{'provider':'test','model':'fixture'}}
        self.manager=RoomJobs(self.store,renderer,lambda row:None)

    def tearDown(self):
        self.release.set();self.manager.pool.shutdown(wait=True);self.temp.cleanup()

    def draft(self):
        return self.manager.create(self.ws,self.session,'art_department','Creative Director','Create a cat image',client_id='one')

    def test_drafts_do_not_execute_and_identity_is_durable(self):
        row=self.draft(); duplicate=self.draft()
        self.assertEqual(row['request_id'],duplicate['request_id']);self.assertEqual(self.calls,[])
        other=RoomJobs(self.store,lambda *a:self.fail('Must not execute'),lambda row:None)
        try:self.assertEqual(other.get(self.ws,'art_department',row['request_id'])['number'],row['number'])
        finally:other.pool.shutdown()

    def test_explicit_send_stale_version_and_idempotency(self):
        row=self.draft()
        with self.assertRaises(ValueError):self.manager.submit(self.ws,'art_department',row['request_id'],1)
        changed=self.manager.update(self.ws,'art_department',row['request_id'],1,{'prompt':'Create a blue cat'})
        with self.assertRaises(ValueError):self.manager.submit(self.ws,'art_department',row['request_id'],1,True)
        accepted=self.manager.submit(self.ws,'art_department',row['request_id'],changed['version'],True)
        self.assertEqual(accepted['attempts'][0]['brief']['prompt'],'Create a blue cat')
        self.manager.submit(self.ws,'art_department',row['request_id'],changed['version'],True)
        self.release.set();self.manager.futures[row['request_id']].result(5)
        self.assertEqual(len(self.calls),1)

    def test_cancel_does_not_report_completion(self):
        row=self.draft();self.manager.submit(self.ws,'art_department',row['request_id'],1,True)
        self.started.wait(2);self.manager.cancel(self.ws,'art_department',row['request_id']);self.release.set()
        self.manager.futures[row['request_id']].result(5)
        final=self.manager.get(self.ws,'art_department',row['request_id']);self.assertEqual(final['status'],'canceled')
        self.assertFalse(final['files'])

    def test_room_scope_and_completion_notice_origin(self):
        row=self.draft()
        with self.assertRaises(ValueError):self.manager.get(self.ws,'control_room',row['request_id'])
        self.manager.submit(self.ws,'art_department',row['request_id'],1,True);self.started.wait(2)
        self.store.set_room(self.ws,self.session,'control_room');self.release.set();self.manager.futures[row['request_id']].result(5)
        final=self.manager.get(self.ws,'art_department',row['request_id']);self.assertEqual(final['status'],'completed')
        self.manager._notice(final)
        notices=[message for message in self.store.load_messages(self.ws,self.session) if message.get('job_notice_key')]
        self.assertEqual(len(notices),1);self.assertEqual(notices[0]['room'],'art_department')
        self.assertEqual(self.store.find_session(self.session)['active_room'],'control_room')

    def test_restart_interrupts_without_repeating_execution(self):
        row=self.draft();row['status']='queued';self.manager._save(row,'test_queued')
        other=RoomJobs(self.store,lambda *a:self.fail('No automatic retry'),lambda row:None)
        try:self.assertEqual(other.get(self.ws,'art_department',row['request_id'])['status'],'interrupted')
        finally:other.pool.shutdown()

    def test_failed_validation_keeps_draft_and_reports_rejection(self):
        row=self.draft();self.manager.validator=lambda row:(_ for _ in ()).throw(ValueError('private fixture detail'))
        with self.assertRaises(ValueError):self.manager.submit(self.ws,'art_department',row['request_id'],1,True)
        final=self.manager.get(self.ws,'art_department',row['request_id'])
        self.assertEqual(final['status'],'draft');self.assertNotIn('private fixture detail',final['error']);self.assertEqual(self.calls,[])

    def test_chat_creation_returns_review_without_calling_model(self):
        with patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager),patch.object(server,'invoke_codex') as invoke:
            result=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':'Make me a meme of a cat','request_id':'chat_draft'})
        self.assertEqual(result['task_type'],'image_precreation');self.assertTrue(result['message']['image_draft'])
        self.assertEqual(result['message']['image_draft_version'],1);invoke.assert_not_called();self.assertEqual(self.calls,[])

    def test_plural_and_multiline_image_requests_open_drafts_without_model_execution(self):
        for index,prompt in enumerate(('Create images of a blue circle','Generate two pictures of a cat','Please create\nthree posters of a dog','Create a .png showing a green triangle','Generate a JPEG showing an orange hexagon','Create a WEBP of a purple circle')):
            with self.subTest(prompt=prompt),patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager),patch.object(server,'invoke_codex') as invoke:
                result=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':prompt,'request_id':f'chat_plural_{index}'})
                self.assertEqual(result['task_type'],'image_precreation')
                self.assertEqual(result['room_job']['status'],'draft')
                self.assertEqual(result['room_job']['original_instructions'],prompt)
                invoke.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_typed_send_recovers_untracked_brief_and_returns_real_review_without_production(self):
        prompt='Create a .png showing a green triangle'
        self.store.append_message(self.ws,self.session,'user',prompt,request_id='legacy_image_request')
        self.store.append_message(self.ws,self.session,'assistant','The brief is ready; use Send to room.')
        with patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager),patch.object(server,'invoke_codex') as invoke:
            result=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':'**Send to room**','request_id':'recover_one'})
            again=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':'send to room','request_id':'recover_two'})
        self.assertEqual(result['task_type'],'image_precreation');self.assertTrue(result['message']['image_draft'])
        self.assertEqual(result['room_job']['original_instructions'],prompt)
        self.assertEqual(result['room_job']['request_id'],again['room_job']['request_id'])
        self.assertEqual(result['room_job']['status'],'draft');self.assertEqual(result['room_job']['attempts'],[])
        self.assertIn('Choose a button',result['message']['text']);invoke.assert_not_called();self.assertEqual(self.calls,[])

    def test_typed_send_does_not_repeat_an_already_accepted_request(self):
        with patch.object(server,'STORE',self.store),patch.object(server,'room_jobs',return_value=self.manager),patch.object(server,'invoke_codex') as invoke:
            result=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':'Create a PNG of a green triangle','request_id':'tracked_png'})
            row=result['room_job'];self.manager.submit(self.ws,'art_department',row['request_id'],1,True)
            again=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':'Send to room','request_id':'send_again'})
        self.assertEqual(again['task_type'],'room_job_status');self.assertFalse(again['message'].get('image_draft'))
        self.release.set();self.manager.futures[row['request_id']].result(5)
        self.assertEqual(len(self.calls),1);invoke.assert_not_called()

    def test_low_chat_selection_and_stronger_review_are_separate(self):
        row=self.manager.create(self.ws,self.session,'art_department','Creative Director','Create an image of a cat. '+('Keep the original requirement. '*30))
        with patch.object(server,'STORE',self.store),patch.object(server,'codex_art_provider',return_value={'configured':True}),patch.object(server,'invoke_codex',return_value={'text':'{"approved":false,"questions":["Which reference should control the layout?"]}','model':'review-model','reasoning_effort':'high'}) as invoke:
            self.manager.validator=server.validate_room_job
            with self.assertRaises(ValueError):self.manager.submit(self.ws,'art_department',row['request_id'],1,True)
        final=self.manager.get(self.ws,'art_department',row['request_id'])
        self.assertEqual(final['status'],'draft');self.assertIn('Which reference',final['error']);self.assertEqual(self.calls,[])
        self.assertEqual(invoke.call_args.args[0]['task_type'],'planning')

    def test_request_identity_is_answered_from_route_metadata(self):
        with patch.object(server,'STORE',self.store),patch.object(server,'invoke_codex') as invoke:
            result=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':'what AI model are you using','chat_model':'luna','chat_reasoning':'medium'})
        self.assertIn('gpt-6-luna',result['message']['text']);self.assertIn('medium',result['message']['text']);invoke.assert_not_called()

    def test_chat_store_is_available_while_submission_is_reviewed(self):
        row=self.draft();reviewing=threading.Event();finish=threading.Event()
        def review(row): reviewing.set();finish.wait(3);return {'approved':True}
        self.manager.validator=review
        thread=threading.Thread(target=lambda:self.manager.submit(self.ws,'art_department',row['request_id'],1,True));thread.start()
        self.assertTrue(reviewing.wait(2))
        self.store.append_message(self.ws,self.session,'user','Independent conversation')
        finish.set();thread.join(3);self.assertFalse(thread.is_alive())
        self.release.set();self.manager.futures[row['request_id']].result(5)

    def test_immutable_submission_and_revision_links(self):
        row=self.draft();self.manager.submit(self.ws,'art_department',row['request_id'],1,True)
        with self.assertRaises(ValueError):self.manager.update(self.ws,'art_department',row['request_id'],2,{'prompt':'changed'})
        self.release.set();self.manager.futures[row['request_id']].result(5)
        revision=self.manager.create(self.ws,self.session,'art_department','Creative Director','Change the color',parent_id=row['request_id'],operation='edit')
        self.assertEqual(revision['parent_request_id'],row['request_id']);self.assertNotEqual(revision['number'],row['number'])

    def test_cancel_reaches_submission_review_without_starting_production(self):
        row=self.draft();reviewing=threading.Event();results=[]
        def review(snapshot):
            reviewing.set()
            self.assertTrue(snapshot['_cancel_event'].wait(3))
            return {'approved':True}
        self.manager.validator=review
        thread=threading.Thread(target=lambda:results.append(self.manager.submit(self.ws,'art_department',row['request_id'],1,True)))
        thread.start();self.assertTrue(reviewing.wait(2))
        self.manager.cancel(self.ws,'art_department',row['request_id']);thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(results[0]['status'],'canceled')
        self.assertEqual(results[0]['attempts'],[]);self.assertEqual(self.calls,[])
