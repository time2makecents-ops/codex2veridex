import hashlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from image_preview import ImagePreview, render
from veridex_core import VeridexStore
import veridex_server


class ImagePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = VeridexStore(Path(self.temp.name))
        initial = self.store.ensure_default()
        self.ws, self.session = initial['workspace']['workspace_id'], initial['session']['session_id']
        self.store.set_room(self.ws, self.session, 'art_department')
        image = Image.new('RGBA', (96, 64))
        image.putdata([(50+x, 60+y, 100, x*2) for y in range(64) for x in range(96)])
        stream = io.BytesIO(); image.save(stream, format='PNG')
        self.original = stream.getvalue()
        self.source = self.store.save_file(self.ws, self.session, 'item.png', self.original, 'image/png')
        self.patch = patch.object(veridex_server, 'STORE', self.store)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.service = ImagePreview(self.store, veridex_server.verify_chat_attachments)
        self.payload = dict(workspace_id=self.ws, session_id=self.session, room_id='art_department',
                            library='session', file_id=self.source['file_id'], sha256=self.source['sha256'])

    def test_preview_is_transient_preserves_alpha_dimensions_and_original(self):
        result = self.service.preview({**self.payload, 'recipe': {'auto': True}})
        with Image.open(io.BytesIO(result)) as image, Image.open(io.BytesIO(self.original)) as original:
            self.assertEqual(image.size, original.size)
            self.assertEqual(image.getchannel('A').tobytes(), original.getchannel('A').tobytes())
            self.assertTrue(image.info.get('icc_profile'))
        self.assertEqual(Path(self.source['path']).read_bytes(), self.original)
        self.assertEqual(len(self.store.list_artifact_ledger(self.ws)), 1)
        self.assertEqual(len(self.store.list_files(self.ws, self.session)), 1)

    def test_remove_background_preserves_rgb_and_combines_existing_alpha(self):
        mask=Image.new('L',(96,64),255)
        mask.paste(0,(0,0,48,64))
        with patch('image_preview.background_mask',return_value=mask):
            result=self.service.preview({**self.payload,'recipe':{'remove_background':True}})
        with Image.open(io.BytesIO(result)) as edited, Image.open(io.BytesIO(self.original)) as original:
            self.assertEqual(edited.size,original.size)
            self.assertEqual(edited.convert('RGB').tobytes(),original.convert('RGB').tobytes())
            self.assertEqual(edited.getpixel((20,20))[3],0)
            self.assertEqual(edited.getpixel((80,20))[3],original.getpixel((80,20))[3])
        self.assertEqual(Path(self.source['path']).read_bytes(),self.original)
        self.assertEqual(len(self.store.list_artifact_ledger(self.ws)),1)

    def test_background_removed_copy_saves_and_sends_with_transparency(self):
        mask=Image.new('L',(96,64),128)
        value={**self.payload,'recipe':{'remove_background':True},'confirm':True,'request_id':'background-save-1'}
        with patch('image_preview.background_mask',return_value=mask): saved=self.service.save(value)
        self.assertTrue(saved['metadata']['image_preview']['recipe']['remove_background'])
        copied=self.service.send({**self.payload,'file_id':saved['file_id'],'sha256':saved['sha256'],
            'target_workspace_id':self.ws,'target_room_id':'control_room','confirm':True,'request_id':'background-send-1'})
        self.assertEqual(Path(copied['path']).read_bytes(),Path(saved['path']).read_bytes())
        with Image.open(copied['path']) as image:
            self.assertEqual(image.mode,'RGBA')
            self.assertLess(image.getchannel('A').getextrema()[1],255)

    def test_save_is_separate_verified_and_idempotent_after_reload(self):
        value = {**self.payload, 'confirm': True, 'request_id': 'save-fixture-1', 'recipe': {'auto': True}}
        saved = self.service.save(value)
        store = VeridexStore(Path(self.temp.name))
        again = ImagePreview(store, veridex_server.verify_chat_attachments).save(value)
        self.assertEqual(saved['file_id'], again['file_id'])
        self.assertEqual(saved['metadata']['image_preview']['source_file_id'], self.source['file_id'])
        self.assertEqual(saved['sha256'], hashlib.sha256(Path(saved['path']).read_bytes()).hexdigest())
        self.assertEqual(len(store.list_artifact_ledger(self.ws)), 2)
        self.assertEqual(Path(self.source['path']).read_bytes(), self.original)
        with self.assertRaises(ValueError):
            self.service.save({**value, 'recipe': {'auto': False}})

    def test_send_cross_workspace_creates_no_session_and_survives_reload(self):
        target = self.store.create_workspace('Destination')['workspace_id']
        value = {**self.payload, 'target_workspace_id': target, 'target_room_id': 'art_department',
                 'confirm': True, 'request_id': 'send-fixture-1'}
        saved = self.service.send(value)
        self.assertEqual(self.store.list_sessions(target), [])
        self.assertEqual(self.store.find_session(self.session)['active_room'], 'art_department')
        self.assertEqual(Path(saved['path']).read_bytes(), self.original)
        self.assertEqual(self.store.list_generated_images(target)[0]['file_id'], saved['file_id'])
        again = ImagePreview(VeridexStore(Path(self.temp.name)), veridex_server.verify_chat_attachments).send(value)
        self.assertEqual(again['file_id'], saved['file_id'])
        self.assertEqual(len(self.store.list_artifact_ledger(target)), 1)

    def test_send_to_other_room_and_attach_copied_image(self):
        value = {**self.payload, 'target_workspace_id': self.ws, 'target_room_id': 'control_room',
                 'confirm': True, 'request_id': 'send-control-1'}
        saved = self.service.send(value)
        target = self.store.create_session(self.ws, 'Review')['session_id']
        self.store.set_room(self.ws, target, 'control_room')
        linked = self.store.link_room_file(self.ws, target, saved['file_id'], 'control_room')
        self.assertEqual(linked['file_id'], saved['file_id'])
        self.assertEqual(self.store.list_room_files(self.ws, 'control_room')[0]['sha256'], self.source['sha256'])

    def test_save_then_failed_send_retains_copy_and_retry_does_not_duplicate(self):
        saved = self.service.save({**self.payload, 'confirm': True, 'request_id': 'save-retry-1', 'recipe': {'auto': True}})
        value = {**self.payload, 'file_id': saved['file_id'], 'sha256': saved['sha256'], 'target_workspace_id': self.ws,
                 'target_room_id': 'missing_room', 'confirm': True, 'request_id': 'send-retry-1'}
        with self.assertRaises(ValueError): self.service.send(value)
        value['target_room_id'] = 'control_room'
        first = self.service.send(value)
        self.assertEqual(first['file_id'], self.service.send(value)['file_id'])
        self.assertEqual(len(self.store.list_artifact_ledger(self.ws)), 3)

    def test_source_confirmation_room_and_destination_boundaries(self):
        with self.assertRaises(ValueError): self.service.save({**self.payload, 'request_id': 'save-invalid'})
        for changed in ({'sha256':'0'*64}, {'file_id':'missing'}, {'session_id':'*'}, {'library':'unknown'}):
            with self.assertRaises((ValueError, KeyError)): self.service.preview({**self.payload, **changed})
        for room in ('lobby', '../control_room', 'missing'):
            with self.assertRaises(ValueError):
                self.service.send({**self.payload, 'target_workspace_id': self.ws, 'target_room_id': room, 'confirm': True, 'request_id':'send-invalid'})
        self.store.set_room(self.ws, self.session, 'control_room')
        with self.assertRaises(ValueError): self.service.preview(self.payload)

    def test_changed_bytes_are_rejected_before_save_or_send(self):
        Path(self.source['path']).write_bytes(b'tampered')
        with self.assertRaises(ValueError): self.service.preview(self.payload)
        self.assertEqual(len(self.store.list_artifact_ledger(self.ws)), 1)

    def test_crop_rotation_formats_and_validation(self):
        result = render(self.original, {'rotation': 90, 'crop': {'left_percent':0, 'top_percent':0, 'right_percent':50, 'bottom_percent':100}})
        with Image.open(io.BytesIO(result)) as image: self.assertEqual(image.size, (64,48))
        for options in ({'remove_background':'yes'}, {'adjustments':{'brightness':101}}, {'rotation':45}, {'auto':'yes'}, {'adjustments':{'unknown':1}}, {'crop':{'left_percent':0}}, {'adjustments':{'brightness':float('nan')}}):
            with self.assertRaises(ValueError): render(self.original, options)
        for mode, format_name in [('RGB','JPEG'), ('RGBA','WEBP')]:
            stream=io.BytesIO();Image.new(mode,(64,64)).save(stream,format=format_name)
            self.assertTrue(render(stream.getvalue(), {'adjustments':{'warmth':5,'highlights':4}}))
        stream=io.BytesIO();Image.new('RGB',(64,64)).save(stream,format='GIF')
        with self.assertRaises(ValueError): render(stream.getvalue(), {})

    def test_http_preview_save_send_content_and_readonly_guard(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),veridex_server.VeridexHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_address[1])
        def post(action,value):
            request=urllib.request.Request(base+'/api/room/images/'+action,data=json.dumps(value).encode(),headers={'Content-Type':'application/json'})
            return urllib.request.urlopen(request,timeout=10)
        try:
            with post('preview',{**self.payload,'recipe':{'auto':True}}) as response:
                self.assertEqual(response.headers['Content-Type'],'image/png');self.assertTrue(response.read())
            with patch.object(veridex_server,'access_mode',return_value='full'):
                with post('save',{**self.payload,'confirm':True,'request_id':'http-save-1','recipe':{'auto':True}}) as response:
                    saved=json.load(response)['file']
                target=self.store.create_workspace('Remote')['workspace_id']
                with post('send',{**self.payload,'confirm':True,'request_id':'http-send-1','target_workspace_id':target,'target_room_id':'art_department'}) as response:
                    copied=json.load(response)['file']
            session=self.store.create_session(target,'Browse')['session_id'];self.store.set_room(target,session,'art_department')
            query=urllib.parse.urlencode(dict(workspace_id=target,session_id=session,room_id='art_department',library='room',file_id=copied['file_id'],sha256=copied['sha256']))
            with urllib.request.urlopen(base+'/api/room/images/content?'+query,timeout=5) as response:
                self.assertEqual(response.read(),self.original)
            with patch.object(veridex_server,'access_mode',return_value='read_only'):
                with self.assertRaises(urllib.error.HTTPError): post('save',{**self.payload,'confirm':True,'request_id':'readonly-1'})
            with patch.object(veridex_server,'access_mode',return_value='full'), patch.object(veridex_server,'active_governance_registry') as registry:
                registry.return_value.preflight.return_value={'allowed':False}
                with self.assertRaises(urllib.error.HTTPError): post('save',{**self.payload,'confirm':True,'request_id':'governance-1'})
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)
