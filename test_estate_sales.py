import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from estate_sales import EstateSales, ROOM
from estate_reports import render
from seller_intake import SellerIntakeCatalog
from veridex_core import VeridexStore
from veridex_governance import GovernanceRegistry
from veridex_rooms import ROOMS
from room_jobs import RoomJobs
import veridex_server as server


class EstateSalesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        catalog=self.root/'rooms.json'
        catalog.write_text(json.dumps({'rooms':ROOMS}),encoding='utf-8')
        self.catalog_patch=patch('veridex_rooms._ROOM_CATALOG_PATH',catalog);self.catalog_patch.start()
        self.store=VeridexStore(self.root/'data');initial=self.store.ensure_default()
        self.ws=initial['workspace']['workspace_id'];self.session=initial['session']['session_id']
        self.store.set_room(self.ws,self.session,ROOM)
        self.intake=SellerIntakeCatalog(self.root/'data');self.service=EstateSales(self.store,self.intake)
        self.sale=self.service.save_project(self.ws,{'name':'Sample sale','scope':'Contents sale'})
        self.project=self.sale['id'];self.jobs=RoomJobs(self.store,server.render_room_job,server.validate_room_job)
        self.patches=[patch.object(server,'STORE',self.store),patch.object(server,'SELLER_INTAKE',self.intake),patch.object(server,'estate_service',return_value=self.service),patch.object(server,'room_jobs',return_value=self.jobs),patch.object(server,'active_governance_registry',return_value=GovernanceRegistry(Path(__file__).parent/'governance/navigator_governance_v1.0.0.json'))]
        for p in self.patches:p.start()

    def tearDown(self):
        self.jobs.pool.shutdown(wait=True)
        for p in reversed(self.patches):p.stop()
        self.catalog_patch.stop();self.tmp.cleanup()

    def call(self,action='state',**value):return server.estate_action({'workspace_id':self.ws,'session_id':self.session,'project_id':self.project,'action':action,**value})

    def item(self,**values):return self.service.add_item(self.ws,self.project,{'title':'Sample bowl','quantity':2,'approved_price':'10.25',**values})

    def test_settings_and_project_edits_are_version_checked(self):
        settings=self.service.save_settings(self.ws,{'name':'Sample business','commission_percent':'25'},0)
        self.assertEqual(settings['version'],1)
        with self.assertRaises(ValueError):self.service.save_settings(self.ws,{'name':'Stale'},0)
        with self.assertRaises(ValueError):self.service.save_project(self.ws,{'name':'Stale'},self.project,0)
        self.assertEqual(EstateSales(self.store,self.intake).snapshot(self.ws,self.project)['project']['name'],'Sample sale')

    def test_projects_and_batches_cannot_cross_workspace_or_client(self):
        batch=self.service.link_batch(self.ws,self.project)
        other=self.service.save_project(self.ws,{'name':'Other sale'})['id']
        with self.assertRaises(ValueError):self.service.link_batch(self.ws,other,batch)
        ws=self.store.create_workspace('Other')['workspace_id']
        with self.assertRaises(ValueError):self.service.snapshot(ws,self.project)
        with self.assertRaises(ValueError):self.service.brief_context(self.ws,other,[self.item()['id']])

    def test_existing_intake_batch_is_linked_without_copying_items(self):
        batch=self.intake.create_batch({'title':'Existing'})['batch_id']
        original=self.intake.create_item({'batch_id':batch,'title':'Existing chair'})
        self.service.link_batch(self.ws,self.project,batch)
        self.assertEqual(self.service.snapshot(self.ws,self.project)['inventory'][0]['id'],original['item_id'])
        self.service.link_batch(self.ws,self.project,batch)
        self.assertEqual(len(self.service.snapshot(self.ws,self.project)['inventory']),1)

    def test_sales_refunds_expenses_and_settlement_use_exact_amounts(self):
        item=self.item()
        self.service.save_project(self.ws,{'commission_percent':'25','fixed_fee':'1.00'},self.project,1)
        sale=self.service.entry(self.ws,self.project,{'type':'sale','item_id':item['id'],'quantity':2,'amount':'20.50','tax':'1.64','payment_method':'card_external'})
        self.service.entry(self.ws,self.project,{'type':'return','item_id':item['id'],'reference_id':sale['id'],'quantity':1})
        self.service.entry(self.ws,self.project,{'type':'expense','amount':'2.00','charged_to':'client'})
        self.service.entry(self.ws,self.project,{'type':'expense','amount':'1.00','charged_to':'business'})
        snap=self.service.snapshot(self.ws,self.project)
        self.assertEqual(snap['finance']['net_sales_cents'],1025)
        self.assertEqual(snap['finance']['tax_collected_cents'],82)
        self.assertEqual(snap['finance']['fees_cents'],356)
        self.assertEqual(snap['finance']['client_proceeds_cents'],469)
        self.assertEqual(snap['inventory'][0]['available'],1)

    def test_unknown_fees_do_not_invent_client_proceeds(self):
        self.assertIsNone(self.service.snapshot(self.ws,self.project)['finance']['client_proceeds_cents'])

    def test_stock_price_and_online_guards(self):
        item=self.item(quantity=1,approved_price='')
        with self.assertRaises(ValueError):self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'10'})
        item=self.service.save_record(self.ws,self.project,'inventory',{'approved_price':'10','online_status':'live','channel':'online'},item['id'],1)
        with self.assertRaises(ValueError):self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'10','channel':'on_site'})
        self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'10','channel':'online'})
        with self.assertRaises(ValueError):self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'10','channel':'online'})

    def test_reservations_pickup_and_refund_limits(self):
        item=self.item()
        reservation=self.service.entry(self.ws,self.project,{'type':'reserve','item_id':item['id'],'quantity':2})
        with self.assertRaises(ValueError):self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'10'})
        self.service.entry(self.ws,self.project,{'type':'release','item_id':item['id'],'reference_id':reservation['id'],'quantity':2})
        sale=self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'10'})
        self.service.entry(self.ws,self.project,{'type':'pickup','item_id':item['id'],'reference_id':sale['id']})
        with self.assertRaises(ValueError):self.service.entry(self.ws,self.project,{'type':'pickup','item_id':item['id'],'reference_id':sale['id']})
        with self.assertRaises(ValueError):self.service.entry(self.ws,self.project,{'type':'return','item_id':item['id'],'reference_id':sale['id'],'amount':'11'})

    def test_client_request_is_required_for_removal(self):
        item=self.item(quantity=1)
        values={'type':'disposition','item_id':item['id'],'disposition':'remove'}
        with self.assertRaises(ValueError):self.service.entry(self.ws,self.project,values)
        with self.assertRaises(ValueError):self.service.entry(self.ws,self.project,{**values,'client_requested':True})
        self.service.save_project(self.ws,{'removal_requested':True},self.project,1)
        self.service.entry(self.ws,self.project,{**values,'client_requested':True,'recipient':'Sample carrier'})
        self.assertEqual(self.service.snapshot(self.ws,self.project)['inventory'][0]['available'],0)

    def test_import_is_atomic_idempotent_and_rejects_conflicting_ids(self):
        item=self.item()
        csv=f'external_id,item_id,quantity,amount\nexternal-1,{item["id"]},1,10.25\n'
        self.assertEqual(self.service.import_sales(self.ws,self.project,csv),{'imported':1,'duplicates':0})
        self.assertEqual(self.service.import_sales(self.ws,self.project,csv),{'imported':0,'duplicates':1})
        with self.assertRaises(ValueError):self.service.import_sales(self.ws,self.project,csv.replace('10.25','10.26'))
        with self.assertRaises(ValueError):self.service.import_sales(self.ws,self.project,csv.replace('external-1','external-2')+f'external-3,{item["id"]},5,50\n')
        self.assertEqual(len(self.service.snapshot(self.ws,self.project)['records']),2)

    def test_closing_requires_inventory_accounting_and_reviewed_terms(self):
        item=self.item(quantity=1)
        with self.assertRaises(ValueError):self.service.save_project(self.ws,{'stage':'complete','settlement_reviewed':True,'fixed_fee':'0'},self.project,1)
        self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'10.25'})
        finished=self.service.save_project(self.ws,{'stage':'complete','settlement_reviewed':True,'fixed_fee':'0'},self.project,1)
        self.assertEqual(finished['stage'],'complete')

    def test_exports_produce_nonempty_files_and_ledgered_artifacts(self):
        self.item()
        for format in ('pdf','csv','xlsx','docx'):
            result=self.call('report',report_type='inventory',format=format)
            row=self.store.resolve_files(self.ws,self.session,[result['file']['file_id']])[0]
            server.verify_chat_attachments(self.ws,[row]);self.assertGreater(row['size'],0)
        content,ext,mime=render(self.service.snapshot(self.ws,self.project),'labels')
        self.assertTrue(content.startswith(b'%PDF'))

    def test_calendar_escapes_newlines_and_uses_saved_dates(self):
        self.service.save_record(self.ws,self.project,'task',{'title':'Task\nSUMMARY:bad','due':'2026-12-01'})
        content,ext,mime=render(self.service.snapshot(self.ws,self.project),'calendar')
        self.assertEqual(ext,'.ics');self.assertIn(b'DTSTART;VALUE=DATE:20261201',content)
        self.assertNotIn(b'\r\nSUMMARY:bad',content)

    def test_specialist_brief_needs_confirmation_and_returns_verified_result_without_navigation(self):
        self.item()
        with patch.object(server,'invoke_codex',return_value={'text':'Draft campaign copy for review.','provider':'codex_cli','model':'fixture','evidence':[]}) as invoke:
            draft=self.call('draft',value={'task_kind':'marketing_plan','prompt':'Prepare campaign copy'})['job']
            invoke.assert_not_called()
            with self.assertRaises(ValueError):self.jobs.submit(self.ws,ROOM,draft['request_id'],draft['version'])
            self.jobs.submit(self.ws,ROOM,draft['request_id'],draft['version'],True)
            self.jobs.futures[draft['request_id']].result(5)
            row=self.jobs.get(self.ws,ROOM,draft['request_id'])
            self.assertEqual(row['status'],'completed',row['error']);self.assertEqual(row['destination_room'],'marketing_room')
            self.assertEqual(self.store.find_session(self.session)['active_room'],ROOM)
            saved=self.store.resolve_files(self.ws,self.session,[row['files'][0]['file_id']])[0]
            server.verify_chat_attachments(self.ws,[saved]);self.assertEqual(saved['room_id'],'marketing_room')
            self.assertNotIn('client',draft['dispatch_context'])
            self.assertIn('approved_brief',invoke.call_args.args[0]['user_prompt'])

    def test_stale_project_blocks_dispatch_before_provider_use(self):
        draft=self.call('draft',value={'task_kind':'marketing_plan','prompt':'Prepare campaign copy'})['job']
        self.service.save_project(self.ws,{'name':'Changed'},self.project,1)
        with patch.object(server,'invoke_codex') as invoke:
            with self.assertRaises(ValueError):self.jobs.submit(self.ws,ROOM,draft['request_id'],draft['version'],True)
            invoke.assert_not_called()
        row=self.jobs.get(self.ws,ROOM,draft['request_id'])
        refreshed=self.call('refresh_brief',room_job_id=row['request_id'],version=row['version'])['job']
        self.assertEqual(refreshed['request_id'],draft['request_id'])
        self.assertEqual(refreshed['dispatch_context']['sale_name'],'Changed')
        self.assertEqual(refreshed['status'],'draft');self.assertEqual(refreshed['attempts'],[])

    def test_cross_project_attachment_and_unavailable_room_are_rejected(self):
        other=self.service.save_project(self.ws,{'name':'Other'})['id']
        file=self.store.save_file(self.ws,self.session,'notes.txt',b'other','text/plain',metadata={'estate_sales':{'project_id':other}})
        with self.assertRaises(ValueError):self.call('draft',value={'task_kind':'marketing_plan','prompt':'Prepare copy','source_file_ids':[file['file_id']]})
        with self.assertRaises(ValueError):self.call('save_record',kind='document',value={'title':'Other doc','file_id':file['file_id']})

    def test_route_requires_estate_room(self):
        self.store.set_room(self.ws,self.session,'lobby')
        with self.assertRaises(ValueError):self.call()

    def test_boss_chat_prepares_refines_and_confirms_without_starting_work(self):
        base={'workspace_id':self.ws,'session_id':self.session,'estate_project_id':self.project}
        with patch.object(server,'invoke_codex') as invoke:
            result=server.chat_response({**base,'text':'Prepare a marketing campaign for this sale','request_id':'campaign-one'})
            draft=result['room_job'];self.assertEqual(draft['destination_room'],'marketing_room')
            refined=server.chat_response({**base,'text':'Use a welcoming tone','image_draft_id':draft['request_id']})
            self.assertEqual(refined['room_job']['request_id'],draft['request_id'])
            self.assertIn('welcoming',refined['room_job']['brief']['prompt'])
            review=server.chat_response({**base,'text':'send','image_draft_id':draft['request_id']})
            self.assertEqual(review['room_job_confirmation']['request_id'],draft['request_id'])
            self.assertEqual(review['room_job']['attempts'],[]);invoke.assert_not_called()
            without_project=server.chat_response({'workspace_id':self.ws,'session_id':self.session,'text':'Create a business plan'})
            self.assertEqual(without_project['task_type'],'estate_project_required');invoke.assert_not_called()
        self.assertIsNone(server.estate_chat_response(self.ws,self.session,{},'How do you price an item?',{},[]))

    def test_boss_normal_chat_receives_only_selected_project_context(self):
        self.service.save_project(self.ws,{'name':'Other private sale'})
        with patch.object(server,'invoke_codex',return_value={'text':'Hello.','provider':'codex_cli','model':'fixture','reasoning_effort':'low','task_type':'simple','evidence':[]}) as invoke:
            server.chat_response({'workspace_id':self.ws,'session_id':self.session,'estate_project_id':self.project,'text':'hello','chat_model':'luna'})
        request=invoke.call_args.args[0]
        self.assertEqual(request['context']['estate_sale']['project']['id'],self.project)
        from codex_gateway import _compact_context
        self.assertIn('Sample sale',_compact_context(request['context']))
        self.assertNotIn('Other private sale',_compact_context(request['context']))

    def test_estate_image_uses_existing_renderer_and_keeps_origin_room(self):
        stream=io.BytesIO();Image.new('RGB',(10,10),'green').save(stream,'PNG')
        assets=[{'content':stream.getvalue(),'extension':'.png','content_type':'image/png','metadata':{'provider':'fixture','model':'fixture'}}]
        draft=self.call('draft',value={'task_kind':'image','prompt':'Create a simple sale flyer'})['job']
        with patch.object(server,'codex_art_provider',return_value={'configured':True}),patch.object(server,'codex_art_assets',return_value=assets):
            self.jobs.submit(self.ws,ROOM,draft['request_id'],draft['version'],True)
            self.jobs.futures[draft['request_id']].result(5)
        row=self.jobs.get(self.ws,ROOM,draft['request_id']);self.assertEqual(row['status'],'completed',row['error'])
        saved=self.store.resolve_files(self.ws,self.session,[row['files'][0]['file_id']])[0]
        self.assertEqual(saved['metadata']['estate_sales']['project_id'],self.project)
        self.assertEqual(saved['room_id'],'art_department');server.verify_chat_attachments(self.ws,[saved])
        self.assertEqual(self.store.find_session(self.session)['active_room'],ROOM)

    def test_selected_photos_are_copied_verified_and_originals_preserved(self):
        item=self.item();stream=io.BytesIO();Image.new('RGB',(10,10),'red').save(stream,'PNG');content=stream.getvalue()
        original=self.intake.add_asset(item['id'],'photo.png',content,'image/png','photo')
        draft=self.call('draft',value={'task_kind':'image','prompt':'Create a flyer using this item photo','item_ids':[item['id']],'include_photos':True})['job']
        self.assertEqual(len(draft['references']),1)
        saved=self.store.resolve_files(self.ws,self.session,draft['brief']['source_file_ids'])
        server.verify_chat_attachments(self.ws,saved)
        self.assertEqual(self.intake.asset_path(original['asset_id'])[1].read_bytes(),content)
        self.assertEqual(saved[0]['metadata']['estate_sales']['project_id'],self.project)

    def test_a_generic_document_cannot_be_bound_to_two_projects(self):
        file=self.store.save_file(self.ws,self.session,'shared.txt',b'synthetic','text/plain')
        self.call('save_record',kind='document',value={'title':'Source','file_id':file['file_id']})
        other=self.service.save_project(self.ws,{'name':'Other'})['id']
        with self.assertRaises(ValueError):self.service.save_record(self.ws,other,'document',{'title':'Wrong','file_id':file['file_id']})

    def test_refund_import_is_idempotent(self):
        item=self.item();sale=self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'10.25'})
        row={'type':'return','item_id':item['id'],'reference_id':sale['id'],'external_id':'refund-1'}
        self.service.entry(self.ws,self.project,row)
        self.assertTrue(self.service.entry(self.ws,self.project,row)['duplicate'])

    def test_final_partial_refund_accounts_for_rounding_remainder(self):
        item=self.item(quantity=3);sale=self.service.entry(self.ws,self.project,{'item_id':item['id'],'quantity':3,'amount':'10','tax':'0.05'})
        for _ in range(3):self.service.entry(self.ws,self.project,{'type':'return','item_id':item['id'],'reference_id':sale['id']})
        finance=self.service.snapshot(self.ws,self.project)['finance']
        self.assertEqual(finance['net_sales_cents'],0);self.assertEqual(finance['tax_collected_cents'],0)

    def test_adjustments_reverse_expenses_without_rewriting_history(self):
        expense=self.service.entry(self.ws,self.project,{'type':'expense','amount':'15','charged_to':'client'})
        self.service.entry(self.ws,self.project,{'type':'adjustment','reference_id':expense['id'],'amount':'5'})
        self.assertEqual(self.service.snapshot(self.ws,self.project)['finance']['client_expenses_cents'],1000)
        self.assertEqual(self.service.snapshot(self.ws,self.project)['records'][0]['amount_cents'],1500)
        with self.assertRaises(ValueError):self.service.entry(self.ws,self.project,{'type':'adjustment','reference_id':expense['id'],'amount':'11'})

    def test_receipt_contains_only_the_selected_transaction(self):
        item=self.item();first=self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'10.25'})
        self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'9.25'})
        with self.assertRaises(ValueError):self.call('report',report_type='receipt',format='csv')
        result=self.call('report',report_type='receipt',format='csv',receipt_id=first['id'])
        saved=self.store.resolve_files(self.ws,self.session,[result['file']['file_id']])[0]
        content=Path(saved['path']).read_text(encoding='utf-8-sig')
        self.assertIn('10.25',content);self.assertNotIn('9.25',content);self.assertNotIn('input_fingerprint',content)

    def test_business_summary_exposes_unconfigured_fees_and_cached_online_review(self):
        item=self.item()
        self.service.entry(self.ws,self.project,{'item_id':item['id'],'amount':'10.25'})
        summary=self.service.summary(self.ws)
        self.assertEqual(summary['currencies']['USD']['net_sales_cents'],1025)
        self.assertEqual(summary['currencies']['USD']['unconfigured_projects'],1)
        from types import SimpleNamespace
        board={'items':[{'item_id':item['id'],'ebay_links':[{'listing':{'status':'active','quantity_sold':0}}]}]}
        with patch.object(server,'workspace_ebay_room',return_value=SimpleNamespace(board=lambda batch:board)):
            result=self.call('online_review')
        self.assertTrue(result['online_observations'][0]['review_needed'])
        self.assertEqual(self.service.snapshot(self.ws,self.project)['inventory'][0]['available'],1)
