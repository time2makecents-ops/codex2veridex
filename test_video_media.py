import io
import tempfile
import unittest
import json
import threading
import urllib.request
import urllib.error
from unittest.mock import patch
from pathlib import Path
from video_media import byte_range, receive_upload
from veridex_core import VeridexStore
import veridex_server as server


class VideoMediaTests(unittest.TestCase):
    def test_http_upload_and_seekable_playback(self):
        with tempfile.TemporaryDirectory() as temp:
            store=VeridexStore(Path(temp));initial=store.ensure_default();ws=initial['workspace']['workspace_id'];session=initial['session']['session_id']
            store.set_room(ws,session,'video_production')
            with patch.object(server,'STORE',store), patch.object(server.VeridexHandler,'_remote_authorized',return_value=True):
                http=server.ThreadingHTTPServer(('127.0.0.1',0),server.VeridexHandler)
                thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
                try:
                    base=f'http://127.0.0.1:{http.server_port}'
                    upload=urllib.request.Request(f'{base}/api/video/upload?workspace_id={ws}&session_id={session}&name=test.mp4',data=b'0123456789',headers={'Content-Type':'video/mp4'},method='POST')
                    with urllib.request.urlopen(upload,timeout=5) as response:file=json.load(response)['file']
                    url=f'{base}/api/files/content?workspace_id={ws}&session_id={session}&file_id={file["file_id"]}'
                    with urllib.request.urlopen(urllib.request.Request(url,headers={'Range':'bytes=2-5'}),timeout=5) as response:
                        self.assertEqual(response.status,206);self.assertEqual(response.headers['Content-Range'],'bytes 2-5/10');self.assertEqual(response.read(),b'2345')
                    with self.assertRaises(urllib.error.HTTPError) as failure:
                        urllib.request.urlopen(urllib.request.Request(url,headers={'Range':'bytes=20-'}),timeout=5)
                    self.assertEqual(failure.exception.code,416)
                    with urllib.request.urlopen(url,timeout=5) as response:self.assertEqual(response.read(),b'0123456789')
                finally:http.shutdown();http.server_close();thread.join(timeout=3)

    def test_single_range_suffix_and_invalid_requests(self):
        for header,expected in [('',(0,9)),('bytes=2-5',(2,5)),('bytes=7-',(7,9)),('bytes=-3',(7,9)),('bytes=0-999',(0,9))]:
            self.assertEqual(byte_range(header,10),expected)
        for header in ('bytes=20-','bytes=5-1','bytes=-0','bytes=0-1,3-4','bytes=-','junk'):
            with self.assertRaises(ValueError):byte_range(header,10)

    def test_stream_upload_registers_room_artifact_without_chat_attachment(self):
        with tempfile.TemporaryDirectory() as temp:
            store=VeridexStore(Path(temp));initial=store.ensure_default();ws=initial['workspace']['workspace_id'];session=initial['session']['session_id']
            store.set_room(ws,session,'video_production')
            save=lambda content:store.save_file(ws,session,'test.mp4',content,'video/mp4',source='video_room',scope='room',scope_ref='video_production')
            file=receive_upload(io.BytesIO(b'test footage'),12,1024,save)
            self.assertEqual(Path(file['path']).read_bytes(),b'test footage')
            self.assertEqual(store.list_room_files(ws,'video_production')[0]['file_id'],file['file_id'])
            chat=store.save_file(ws,session,'chat.png',b'chat','image/png',source='video_chat')
            self.assertNotIn(chat['file_id'],[r['file_id'] for r in store.list_room_files(ws,'video_production')])
            self.assertIn(chat['file_id'],[r['file_id'] for r in store.list_files(ws,session)])
            self.assertEqual(len(store.list_artifact_ledger(ws)),2)
            store.set_room(ws,session,'hr_department')
            with self.assertRaises(ValueError):
                store.save_file(ws,session,'late.mp4',b'late',expected_room='video_production')
            self.assertEqual(len(store.list_artifact_ledger(ws)),2)

    def test_truncated_empty_and_oversize_uploads_never_save(self):
        saved=[]
        for data,length,maximum in [(b'ab',3,10),(b'',0,10),(b'abc',3,2)]:
            with self.assertRaises(ValueError):receive_upload(io.BytesIO(data),length,maximum,saved.append)
        self.assertEqual(saved,[])


if __name__=='__main__':unittest.main()
