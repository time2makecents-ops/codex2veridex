"""Workspace-scoped estate projects, Intake links, and deterministic operations."""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date
import csv
import io
import json
import hashlib
import sqlite3
import threading
import uuid

from veridex_core import utc_now

ROOM = 'estate_sales_room'
STAGES = ['inquiry','walkthrough','proposal','booked','preparation','advertising','sale','closeout','complete','canceled','archived']
SKILLS = {
    'business_plan': ('estate_sales_room','planning','Business launch and service plan'),
    'sale_plan': ('estate_sales_room','planning','Client walkthrough and sale operating plan'),
    'pricing_research': ('antiques_department','search_deep','Item identification and sourced pricing research'),
    'marketing_plan': ('marketing_room','planning','Campaign plan and channel copy'),
    'image': ('art_department','planning','Flyer, sign, or image'),
    'online_listing': ('ebay','conversation','Online listing preparation'),
    'client_email': ('my_office','conversation','Client email draft'),
    'agreement': ('law_office','planning','Agreement draft and review questions'),
    'finance_review': ('finance_department','planning','Review the recorded budget and settlement'),
    'video_brief': ('video_production','planning','Walkthrough or promotional video brief'),
    'cleanup_plan': ('estate_sales_room','planning','Client-requested cleanup and removal plan'),
}


def text(value, limit=12000):
    value=str(value or '').strip()
    if len(value)>limit: raise ValueError(f'Text exceeds {limit} characters')
    return value


def money(value, optional=False):
    if value in ('',None) and optional:return None
    try:
        amount=Decimal(str(value))
        if not amount.is_finite() or amount<0 or amount>Decimal('100000000'):raise ValueError('Invalid amount')
        return int((amount*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except (InvalidOperation,TypeError):raise ValueError('Enter a valid money amount') from None


def integer(value, minimum=0):
    try: number=int(str(value))
    except (ValueError,TypeError):raise ValueError('Enter a whole number') from None
    if number<minimum or number>1000000:raise ValueError('Quantity is out of range')
    return number


def day(value):
    value=text(value,10)
    if value:date.fromisoformat(value)
    return value


class EstateSales:
    def __init__(self,store,intake):
        self.store,self.intake=store,intake
        self.path=store.root/'estate_sales'/'catalog.sqlite3'
        self.lock=threading.RLock()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS projects(ws TEXT,id TEXT,version INTEGER,body TEXT,PRIMARY KEY(ws,id));
              CREATE TABLE IF NOT EXISTS settings(ws TEXT PRIMARY KEY,version INTEGER,body TEXT);
              CREATE TABLE IF NOT EXISTS records(ws TEXT,project TEXT,id TEXT,kind TEXT,version INTEGER,body TEXT,PRIMARY KEY(ws,project,id));
              CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,ws TEXT,project TEXT);
              CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,ws TEXT,project TEXT,event TEXT,record TEXT,at TEXT);
            ''')

    @contextmanager
    def connection(self):
        with self.lock:
            db=sqlite3.connect(self.path,timeout=20);db.row_factory=sqlite3.Row
            try:
                db.execute('BEGIN IMMEDIATE');yield db;db.commit()
            except Exception:db.rollback();raise
            finally:db.close()

    def event(self,db,ws,project,event,row):
        db.execute('INSERT INTO events(ws,project,event,record,at) VALUES(?,?,?,?,?)',(ws,project,event,json.dumps(row),utc_now()))

    @staticmethod
    def unpack(row):
        if row is None:raise ValueError('Record is unavailable in this workspace and project')
        return {**json.loads(row['body']),'id':row['id'],'version':row['version']}

    def _project(self,db,ws,project):
        self.store.get_workspace(ws)
        return self.unpack(db.execute('SELECT * FROM projects WHERE ws=? AND id=?',(ws,project)).fetchone())

    def settings(self,ws):
        self.store.get_workspace(ws)
        with self.connection() as db:
            row=db.execute('SELECT * FROM settings WHERE ws=?',(ws,)).fetchone()
            return {**json.loads(row['body']),'version':row['version']} if row else {'version':0,'name':'','currency':'USD','service_area':'','email':'','phone':'','services':'','commission_percent':'','fixed_fee':'','brand_notes':'','supplies':'','agreement_notes':''}

    def save_settings(self,ws,value,version):
        current=self.settings(ws)
        allowed=('name','service_area','email','phone','services','brand_notes','supplies','agreement_notes')
        row={**current,**{key:text(value[key]) for key in allowed if key in value}}
        currency=text(value.get('currency',current['currency']),3).upper()
        if len(currency)!=3 or not currency.isalpha():raise ValueError('Use a three-letter currency code')
        row['currency']=currency
        for field in ('commission_percent','fixed_fee'):
            row[field]=text(value.get(field,current[field]),30)
            amount=money(row[field],True)
            if field=='commission_percent' and amount is not None and amount>10000:raise ValueError('Commission must be between 0 and 100 percent')
        with self.connection() as db:
            old=db.execute('SELECT version FROM settings WHERE ws=?',(ws,)).fetchone()
            if (old['version'] if old else 0)!=int(version):raise ValueError('Business settings changed; reload before saving')
            row['version']=int(version)+1
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?,?)',(ws,row['version'],json.dumps(row)))
            self.event(db,ws,'','business_saved',{'version':row['version']})
        return row

    def save_project(self,ws,value,project='',version=0):
        settings=self.settings(ws)
        with self.connection() as db:
            old=self._project(db,ws,project) if project else {'stage':'inquiry','created_at':utc_now(),'commission_percent':settings['commission_percent'],'fixed_fee':settings['fixed_fee'],'currency':settings['currency']}
            if project and old['version']!=int(version):raise ValueError('Project changed; reload before saving')
            row={**old,**{key:text(value[key]) for key in ('name','client_name','client_email','client_phone','address','scope','exclusions','access_notes','agreement_notes','public_description','commission_percent','fixed_fee','discount_rules','cleanup_instructions','service_area') if key in value}}
            if not row.get('name'):raise ValueError('Give the sale a name')
            row['stage']=value.get('stage',old['stage'])
            if row['stage'] not in STAGES:raise ValueError('Invalid project stage')
            for key in ('sale_date','end_date','deadline'):
                row[key]=day(value.get(key,old.get(key,'')))
            for key in ('cleanup_requested','removal_requested','cleanup_completed','settlement_reviewed'):
                row[key]=value.get(key,old.get(key,False)) is True
            for key in ('commission_percent','fixed_fee'):
                amount=money(row.get(key,''),True)
                if key=='commission_percent' and amount is not None and amount>10000:raise ValueError('Invalid commission percentage')
            project=project or 'es_'+uuid.uuid4().hex[:16]
            if row['stage']=='complete':
                if not row['settlement_reviewed']:raise ValueError('Review the settlement before completing the sale')
                if row['cleanup_requested'] and not row['cleanup_completed']:raise ValueError('Record completion of the requested cleanup')
                inventory=self._inventory(db,ws,project)
                if any(item['available'] or item['reserved'] for item in inventory):raise ValueError('Account for remaining or reserved inventory before completing')
                if row.get('commission_percent','')=='' and row.get('fixed_fee','')=='':raise ValueError('Set the agreed fees, including zero if appropriate')
            row.update(id=project,version=int(version)+1,updated_at=utc_now())
            db.execute('INSERT OR REPLACE INTO projects VALUES(?,?,?,?)',(ws,project,row['version'],json.dumps(row)))
            self.event(db,ws,project,'project_saved',row)
        return row

    def projects(self,ws):
        self.store.get_workspace(ws)
        with self.connection() as db:return [self.unpack(row) for row in db.execute('SELECT * FROM projects WHERE ws=? ORDER BY rowid DESC',(ws,))]

    def records(self,db,ws,project,kind=None):
        rows=db.execute('SELECT * FROM records WHERE ws=? AND project=? ORDER BY rowid',(ws,project))
        return [self.unpack(row) for row in rows if kind is None or row['kind']==kind]

    def link_batch(self,ws,project,batch=''):
        with self.connection() as db:
            sale=self._project(db,ws,project)
            if not batch:batch=self.intake.create_batch({'title':sale['name']})['batch_id']
            intake_batch=self.intake.get_batch(batch)
            old=db.execute('SELECT * FROM batches WHERE id=?',(batch,)).fetchone()
            if old and (old['ws'],old['project'])!=(ws,project):raise ValueError('Batch already belongs to another project')
            db.execute('INSERT OR IGNORE INTO batches VALUES(?,?,?)',(batch,ws,project))
            self.event(db,ws,project,'batch_linked',{'batch_id':batch})
            known={row['id'] for row in self.records(db,ws,project,'inventory')}
        for item in intake_batch['items']:
            if item['item_id'] not in known:self.save_record(ws,project,'inventory',{'item_id':item['item_id']})
        return batch

    def add_item(self,ws,project,value):
        with self.connection() as db:
            sale=self._project(db,ws,project)
            if sale['stage'] in {'complete','archived','canceled'}:raise ValueError('Reopen the project before changing inventory')
            batch=text(value.get('batch_id'))
            if not batch:
                row=db.execute('SELECT id FROM batches WHERE ws=? AND project=? LIMIT 1',(ws,project)).fetchone()
                batch=row['id'] if row else ''
            elif not db.execute('SELECT id FROM batches WHERE ws=? AND project=? AND id=?',(ws,project,batch)).fetchone():raise ValueError('Batch does not belong to this project')
        if not batch:batch=self.link_batch(ws,project)
        item=self.intake.create_item({'batch_id':batch,'title':text(value.get('title'),200),'description':text(value.get('description'))})
        return self.save_record(ws,project,'inventory',{**value,'item_id':item['item_id']})

    def save_record(self,ws,project,kind,value,record='',version=0):
        if kind not in {'inventory','task','document'}:raise ValueError('Unsupported editable record')
        with self.connection() as db:
            sale=self._project(db,ws,project)
            if kind=='inventory' and sale['stage'] in {'complete','archived','canceled'}:raise ValueError('Reopen the project before changing inventory')
            old=self.unpack(db.execute('SELECT * FROM records WHERE ws=? AND project=? AND id=? AND kind=?',(ws,project,record,kind)).fetchone()) if record else {}
            if record and old['version']!=int(version):raise ValueError('Record changed; reload before saving')
            row={**old,'kind':kind}
            if kind=='inventory':
                item_id=old.get('item_id') or text(value.get('item_id'))
                item=self.intake.get_item(item_id)
                if not db.execute('SELECT id FROM batches WHERE ws=? AND project=? AND id=?',(ws,project,item['batch_id'])).fetchone():raise ValueError('Item is not linked to this project')
                record=item_id
                exists=db.execute('SELECT version FROM records WHERE ws=? AND project=? AND id=?',(ws,project,record)).fetchone()
                if not old and exists:raise ValueError('Item is already linked; reopen it to edit')
                row['item_id']=item_id
                row['quantity']=integer(value.get('quantity',old.get('quantity',1)),1)
                for key in ('location','condition','pricing_evidence','lot','online_url'):
                    row[key]=text(value.get(key,old.get(key,'')))
                for key in ('suggested_price','approved_price'):
                    row[key+'_cents']=money(value[key],True) if key in value else old.get(key+'_cents')
                row['channel']=value.get('channel',old.get('channel','on_site'))
                row['online_status']=value.get('online_status',old.get('online_status','none'))
                if row['channel'] not in {'on_site','online','client_keep'} or row['online_status'] not in {'none','draft','live','withdrawn','sold'}:raise ValueError('Invalid inventory channel or listing status')
                previous=next((item for item in self._inventory(db,ws,project) if item['id']==record),None)
                if previous and row['quantity']<previous['sold']+previous['disposed']+previous['reserved']:raise ValueError('Quantity cannot be below recorded sales, reservations, and disposition')
            else:
                for key in ('title','notes','assignee','stage','document_type','file_id'):
                    row[key]=text(value.get(key,old.get(key,'')))
                if not row['title']:raise ValueError('Title is required')
                row['status']=text(value.get('status',old.get('status','todo' if kind=='task' else 'draft')))
                allowed={'todo','done','blocked'} if kind=='task' else {'draft','approved','signed'}
                if row['status'] not in allowed:raise ValueError('Invalid record status')
                row['due']=day(value.get('due',old.get('due','')))
                if kind=='document' and row['file_id']:
                    for binding in db.execute("SELECT ws,project,body FROM records WHERE kind='document'"):
                        if json.loads(binding['body']).get('file_id')==row['file_id'] and (binding['ws'],binding['project'])!=(ws,project):raise ValueError('Document is already assigned to another project')
            record=record or 'er_'+uuid.uuid4().hex[:16]
            row.update(id=record,version=int(version)+1,updated_at=utc_now())
            db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?)',(ws,project,record,kind,row['version'],json.dumps(row)))
            self.event(db,ws,project,kind+'_saved',row)
            return row

    def _inventory(self,db,ws,project):
        records=self.records(db,ws,project);ledger=[row for row in records if row['kind']=='entry']
        result=[]
        for row in (r for r in records if r['kind']=='inventory'):
            item=self.intake.get_item(row['item_id'])
            entries=[r for r in ledger if r.get('item_id')==row['id']]
            sold=sum(r['quantity']*(1 if r['type']=='sale' else -1 if r['type']=='return' else 0) for r in entries)
            disposed=sum(r['quantity'] for r in entries if r['type']=='disposition')
            reserved=sum(r['quantity']*(1 if r['type']=='reserve' else -1 if r['type']=='release' else 0) for r in entries)
            result.append({**row,'title':item['title'],'description':item['description'],'assets':item.get('assets',[]),'sold':sold,'disposed':disposed,'reserved':reserved,'available':row['quantity']-sold-disposed-reserved})
        return result

    def entry(self,ws,project,value,db=None):
        if db is None:
            with self.connection() as connection:return self.entry(ws,project,value,connection)
        sale=self._project(db,ws,project)
        entry_type=value.get('type','sale')
        if entry_type not in {'sale','return','expense','reserve','release','pickup','disposition','payout','adjustment'}:raise ValueError('Invalid operation')
        external=text(value.get('external_id'),160)
        entries=self.records(db,ws,project,'entry')
        row={'kind':'entry','type':entry_type,'external_id':external,'notes':text(value.get('notes')),'date':day(value.get('date') or date.today().isoformat()),'item_id':text(value.get('item_id')),'reference_id':text(value.get('reference_id')),'quantity':integer(value.get('quantity',1),1),'amount_cents':0,'tax_cents':0,'payment_method':text(value.get('payment_method','cash'),40),'channel':text(value.get('channel','on_site'),40),'charged_to':text(value.get('charged_to','business'),20),'recipient':text(value.get('recipient'),160)}
        if row['payment_method'] not in {'cash','card_external','bank','other'}:raise ValueError('Choose cash, external card, bank, or other')
        if row['channel'] not in {'on_site','online'}:raise ValueError('Invalid sale channel')
        if row['charged_to'] not in {'client','business'}:raise ValueError('Invalid expense allocation')
        if entry_type in {'sale','expense','payout','adjustment'}:
            row['amount_cents']=money(value.get('amount',0))
            if row['amount_cents'] is None:raise ValueError('Amount is required')
        if entry_type=='sale':row['tax_cents']=money(value.get('tax',0))
        if entry_type=='disposition':row.update(disposition=value.get('disposition','keep'),client_requested=value.get('client_requested') is True)
        if external:
            duplicate=next((old for old in entries if old.get('external_id')==external),None)
            if duplicate and not value.get('date'):row['date']=duplicate['date']
            fingerprint=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
            if duplicate:
                if duplicate.get('input_fingerprint'):
                    matches=duplicate['input_fingerprint']==fingerprint
                else:
                    matches=all(duplicate.get(key)==val for key,val in row.items() if not (entry_type=='return' and key in {'amount_cents','tax_cents'} and ('amount' if key=='amount_cents' else 'tax') not in value))
                if not matches:raise ValueError('External transaction ID already has different contents')
                return {**duplicate,'duplicate':True}
            row['input_fingerprint']=fingerprint
        if sale['stage'] in {'complete','archived','canceled'}:raise ValueError('Reopen the project before recording more operations')
        if entry_type=='adjustment':
            original=next((entry for entry in entries if entry['id']==row['reference_id'] and entry['type'] in {'expense','payout'}),None)
            if not original:raise ValueError('Select the original expense or payout')
            adjusted=sum(entry['amount_cents'] for entry in entries if entry['type']=='adjustment' and entry['reference_id']==original['id'])
            if adjusted+row['amount_cents']>original['amount_cents']:raise ValueError('Adjustment exceeds the original amount')
            row.update(adjustment_for=original['type'],charged_to=original['charged_to'])
        if entry_type not in {'expense','payout','adjustment'}:
            inventory=next((r for r in self._inventory(db,ws,project) if r['id']==row['item_id']),None)
            if not inventory:raise ValueError('Select inventory from this project')
            if entry_type in {'sale','reserve','disposition'}:
                if row['quantity']>inventory['available']:raise ValueError('Not enough available inventory')
                if inventory['channel']=='client_keep' and entry_type!='disposition':raise ValueError('Client-retained items are not for sale')
                if inventory['online_status']=='live' and (entry_type!='sale' or row['channel']!='online'):raise ValueError('Resolve the live online listing before using this stock on site or removing it')
            if entry_type=='sale' and inventory['approved_price_cents'] is None:raise ValueError('Approve the item price before recording a sale')
            if entry_type in {'return','pickup','release'}:
                original=next((r for r in entries if r['id']==row['reference_id']),None)
                expected='reserve' if entry_type=='release' else 'sale'
                if not original or original['type']!=expected or original['item_id']!=row['item_id']:raise ValueError('Choose the original sale or reservation in this project')
                used=sum(r['quantity'] for r in entries if r['type']==entry_type and r['reference_id']==original['id'])
                if used+row['quantity']>original['quantity']:raise ValueError('Quantity exceeds the remaining original transaction')
                if entry_type=='return':
                    previous=[r for r in entries if r['type']=='return' and r['reference_id']==original['id']]
                    last=used+row['quantity']==original['quantity']
                    default_amount=Decimal(original['amount_cents']-sum(r['amount_cents'] for r in previous))/100 if last else Decimal(original['amount_cents'])*row['quantity']/original['quantity']/100
                    default_tax=Decimal(original.get('tax_cents',0)-sum(r.get('tax_cents',0) for r in previous))/100 if last else Decimal(original.get('tax_cents',0))*row['quantity']/original['quantity']/100
                    row['amount_cents']=money(value.get('amount',default_amount))
                    row['tax_cents']=money(value.get('tax',default_tax))
                    if row['amount_cents']+sum(r['amount_cents'] for r in previous)>original['amount_cents'] or row['tax_cents']+sum(r.get('tax_cents',0) for r in previous)>original.get('tax_cents',0):raise ValueError('Refund exceeds the original payment')
                elif entry_type=='pickup' and used+row['quantity']+sum(r['quantity'] for r in entries if r['type']=='return' and r['reference_id']==original['id'])>original['quantity']:raise ValueError('Returned inventory is no longer awaiting pickup')
            if entry_type=='disposition':
                row['disposition']=value.get('disposition','keep')
                if row['disposition'] not in {'keep','donate','consign','remove','dispose'}:raise ValueError('Invalid inventory disposition')
                if value.get('client_requested') is not True:raise ValueError('Record the client request before disposition')
                if row['disposition'] in {'remove','dispose'} and not sale.get('removal_requested'):raise ValueError('Client removal service has not been requested')
                row['client_requested']=True
        row.update(id='ee_'+uuid.uuid4().hex[:16],version=1,created_at=utc_now())
        db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',(ws,project,row['id'],'entry',1,json.dumps(row)))
        self.event(db,ws,project,'entry_recorded',row)
        return row

    def import_sales(self,ws,project,contents):
        if len(contents)>1000000:raise ValueError('CSV is too large')
        parsed=list(csv.DictReader(io.StringIO(contents)))
        if len(parsed)>2000:raise ValueError('Import at most 2000 transactions at a time')
        if not parsed or any(not row.get('external_id') for row in parsed):raise ValueError('Each imported row needs an external_id')
        with self.connection() as db:
            result=[self.entry(ws,project,row,db) for row in parsed]
        return {'imported':sum(not row.get('duplicate',False) for row in result),'duplicates':sum(row.get('duplicate',False) for row in result)}

    def snapshot(self,ws,project):
        with self.connection() as db:
            sale=self._project(db,ws,project);records=self.records(db,ws,project)
            inventory=self._inventory(db,ws,project)
            batches=[r['id'] for r in db.execute('SELECT id FROM batches WHERE ws=? AND project=?',(ws,project))]
        entries=[r for r in records if r['kind']=='entry']
        gross=sum(r['amount_cents'] for r in entries if r['type']=='sale')
        refunds=sum(r['amount_cents'] for r in entries if r['type']=='return')
        tax=sum(r.get('tax_cents',0)*(1 if r['type']=='sale' else -1 if r['type']=='return' else 0) for r in entries)
        net=gross-refunds
        client_cost=sum(r['amount_cents']*(1 if r['type']=='expense' else -1) for r in entries if (r['type']=='expense' or r['type']=='adjustment' and r.get('adjustment_for')=='expense') and r['charged_to']=='client')
        business_cost=sum(r['amount_cents']*(1 if r['type']=='expense' else -1) for r in entries if (r['type']=='expense' or r['type']=='adjustment' and r.get('adjustment_for')=='expense') and r['charged_to']=='business')
        bps=money(sale.get('commission_percent',''),True);fixed=money(sale.get('fixed_fee',''),True)
        fees=None if bps is None and fixed is None else int((Decimal(net)*Decimal(bps or 0)/10000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))+(fixed or 0)
        payouts=sum(r['amount_cents']*(1 if r['type']=='payout' else -1) for r in entries if r['type']=='payout' or r['type']=='adjustment' and r.get('adjustment_for')=='payout')
        finance={'gross_cents':gross,'refunds_cents':refunds,'net_sales_cents':net,'tax_collected_cents':tax,'client_expenses_cents':client_cost,'business_expenses_cents':business_cost,'fees_cents':fees,'client_proceeds_cents':None if fees is None else net-fees-client_cost,'business_margin_cents':None if fees is None else fees-business_cost,'payouts_cents':payouts,'remaining_payout_cents':None if fees is None else net-fees-client_cost-payouts}
        return {'project':sale,'inventory':inventory,'records':records,'batch_ids':batches,'finance':finance}

    def brief_context(self,ws,project,item_ids):
        snap=self.snapshot(ws,project)
        selected=[item for item in snap['inventory'] if item['id'] in item_ids]
        if len(selected)!=len(set(item_ids)):raise ValueError('Reference item is not in this project')
        return {'sale_name':snap['project']['name'],'public_description':snap['project'].get('public_description',''),'sale_date':snap['project'].get('sale_date',''),'items':[{key:item.get(key) for key in ('id','title','description','condition','approved_price_cents','pricing_evidence')} for item in selected]}

    def history(self,ws,project):
        with self.connection() as db:
            self._project(db,ws,project)
            return [dict(row) for row in db.execute('SELECT sequence,event,at FROM events WHERE ws=? AND project=? ORDER BY sequence DESC LIMIT 100',(ws,project))]

    def summary(self,ws):
        result={'active_projects':0,'open_tasks':0,'currencies':{}}
        for project in self.projects(ws):
            snapshot=self.snapshot(ws,project['id']);finance=snapshot['finance']
            result['active_projects']+=project['stage'] not in {'complete','canceled','archived'}
            result['open_tasks']+=sum(row['kind']=='task' and row['status']!='done' for row in snapshot['records'])
            currency=result['currencies'].setdefault(project['currency'],{'net_sales_cents':0,'known_business_margin_cents':0,'unconfigured_projects':0})
            currency['net_sales_cents']+=finance['net_sales_cents']
            currency['known_business_margin_cents']+=finance['business_margin_cents'] or 0
            currency['unconfigured_projects']+=finance['business_margin_cents'] is None
        return result
