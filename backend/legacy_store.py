"""Direct access to existing MySQL tables and the legacy 回應 JSON directory.

No schema creation, shadow tables, SQLite cache, or copied business database.
"""
import copy
import hashlib
import json
import math
import os
import re
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import MetaData, Table, select, insert, update, func, text, or_
from legacy_schema import ASSETS, RECORDS, array

TZ = timezone(timedelta(hours=8))
FOLDERS = {'A':'主表','B':'發車紀錄表','C':'回程紀錄表','D':'工作間預約表','E':'儀器借用表'}
STATES = ['PENDING','DEPARTURE','DEPARTURE_ARRIVED','RETURN','RETURN_ARRIVED']
REASONS = ['工案','材料送貨','新開發案','客戶拜訪','成交案回訪','參展','其他']
E_REASONS = ['開案','成案（施工前量測）','成案（完工量測）','成案（服務回訪）','儀器設備保養／校正','儀器設備維修','其它']
FIELD_MAP = json.loads(Path(__file__).with_name('legacy_form_fields.json').read_text())
# These are the fixed room choices in the existing form, not database assets.
ROOMS = [('1F','批覆區','1-1'),('1F','批覆區','1-2'),('1F','拆組裝區','整區'),('1F','裝載區','整區'),
    ('1F','汞浦試壓區','整區'),('1F','噴砂室','整區'),('1F','研磨與氣動除鏽區','6-1'),
    ('1F','研磨與氣動除鏽區','6-2'),('1F','研磨與氣動除鏽區','6-3'),('1F','產品說明室','整區'),
    ('2F','會議室','整間'),('2F','會客室','整間')]
CHECKS_B=['擋風玻璃清潔','照後鏡清潔','油量檢查','輪胎檢查','車輛內部清潔','車體外部檢查','隨車設備檢查']
CHECKS_C=['車輛內部清潔','車輛內部物品歸位','車輛鑰匙歸位','油量檢查','車體外部檢查','隨車設備檢查']
ASSETS['vehicle'][4].update(phone='phone_number',license_files='license_file_uuid',vehicle_files='vehicle_data_file_uuid',contract_files='contract_file_uuid')
RECORDS['insurance'][1].update(roadside='roadside_assistance',policy_files='policy_file_uuid',claim_files='claim_file_uuid')
for cat,col in [('cost','upload_file'),('maintenance','attachment_uuids'),('garage','attachment_uuids')]: RECORDS[cat][1]['attachments']=col
FILE_KEYS={'license_files','vehicle_files','contract_files','policy_files','claim_files','attachments'}

def fail(message, status=422): raise HTTPException(status, message)
def now(): return datetime.now(TZ).replace(tzinfo=None)
def iso(value): return value.isoformat(timespec='seconds')+'+08:00' if isinstance(value,datetime) else str(value or '')
def parse(value):
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d.astimezone(TZ).replace(tzinfo=None) if d.tzinfo else d
    except (ValueError,TypeError): fail('請填寫有效日期與時間')
def dump(value): return json.dumps(value,ensure_ascii=False,default=str)
def fingerprint(value): return int(hashlib.sha256(dump(value).encode()).hexdigest()[:12],16)
def clean(value): return {k:v for k,v in value.items() if not k.startswith('_')}
def scalar(value): return '' if value is None else value if isinstance(value,(str,int,float,bool)) else str(value)
def resource_id(kind, pk): return int(pk)*10 + {'vehicle':1,'equipment':2}[kind]
def room_id(label): return int(hashlib.sha256(label.encode()).hexdigest()[:11],16)*10+3

def room(label,floor='',area='',unit=''):
    return {'id':room_id(label),'kind':'room','label':label,'floor':floor,'area':area or label,'unit':unit or '整區'}
def room_labels(value):
    # Old D records store several selections joined by commas in one SQL row.
    value=str(value or '')
    bracket=re.search(r'\((.*?)\)',value)
    return array(bracket.group(1)) if bracket else array(value)

class Store:
    def __init__(self, engine, root, data):
        self.engine=engine; self.root=Path(root); self.data=Path(data)
        self.responses=Path(os.getenv('AMS_LEGACY_RESPONSES_DIR', str(self.root.parent/'polimax_carAPI_on'/'回應')))
        self.files=self.data/'files';self.files.mkdir(parents=True,exist_ok=True)
        metadata=MetaData()
        names=[v[0] for v in ASSETS.values()]+[v[0] for v in RECORDS.values()]+['formio_responses','form_flows']
        self.tables={name:Table(name,metadata,autoload_with=engine) for name in names}
        self.lock_name='polimax:'+hashlib.sha256(str(engine.url.database).encode()).hexdigest()[:32]

    @contextmanager
    def session(self, write=False):
        with self.engine.connect() as connection:
            repo=Repository(self,connection)
            locked=False
            try:
                if write:
                    locked=connection.execute(text('SELECT GET_LOCK(:name, 15)'),{'name':self.lock_name}).scalar()==1
                    if not locked: fail('其他表單正在儲存，請稍後重試',409)
                    connection.commit()
                yield repo
                if write:
                    repo.install_files()
                    connection.commit()
                else: connection.rollback()
            except BaseException:
                connection.rollback();repo.restore_files();raise
            finally:
                if locked:
                    connection.execute(text('SELECT RELEASE_LOCK(:name)'),{'name':self.lock_name})
                    connection.commit()

    def path(self, fid):
        if not re.fullmatch(r'\d{5}[ABCDE]\d{4,}',fid): fail('無效表單編號',404)
        return self.responses/FOLDERS[fid[5]]/(fid+'.json')

    def read(self, fid):
        path=self.path(fid)
        if not path.exists(): return {}
        try:
            value=json.loads(path.read_text(encoding='utf-8'))
            return value.get('content',value) if isinstance(value,dict) else {}
        except (ValueError,OSError): fail('既有表單 JSON 無法讀取，請檢查 '+fid,503)

    def attachment(self, item):
        if isinstance(item,dict):
            ident=item.get('id') or item.get('uuid') or item.get('data',{}).get('uuid') or item.get('name','')
            return {**item,'id':str(ident),'name':item.get('originalName') or item.get('name') or str(ident)}
        ident=str(item)
        path=self.files/(ident+'.json') if re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',ident) else None
        if path and path.exists(): return json.loads(path.read_text())
        return {'id':ident,'name':ident,'legacy':True}

class Repository:
    def __init__(self,store,connection):
        self.store=store;self.c=connection;self.t=store.tables;self.pending={};self.installed=[]
    def install_files(self):
        for path,value in self.pending.items():
            path.parent.mkdir(parents=True,exist_ok=True)
            previous=path.read_bytes() if path.exists() else None
            temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
            try:
                with temporary.open('wb') as f: f.write(value);f.flush();os.fsync(f.fileno())
                if previous is not None:
                    backup=path.with_name(path.stem+'_'+now().strftime('%Y%m%d%H%M%S%f')+'.bak.json')
                    backup.write_bytes(previous)
                os.replace(temporary,path);self.installed.append((path,previous))
            finally: temporary.unlink(missing_ok=True)
    def restore_files(self):
        for path,previous in reversed(self.installed):
            if previous is None:path.unlink(missing_ok=True)
            else:
                temp=path.with_name('.restore-'+uuid.uuid4().hex)
                temp.write_bytes(previous);os.replace(temp,path)
    def save_json(self,fid,raw):
        self.pending[self.store.path(fid)]=dump({'content':raw} if fid[5]=='A' else raw).encode()
    def raw(self,fid):
        path=self.store.path(fid)
        if path in self.pending:
            value=json.loads(self.pending[path]);return value.get('content',value)
        return self.store.read(fid)
    def rows(self,name,condition=None):
        q=select(self.t[name])
        if condition is not None:q=q.where(condition)
        return self.c.execute(q).mappings().all()
    def decode_fields(self,row,fields):
        data={key:scalar(row[col]) for key,col in fields.items()}
        for key in FILE_KEYS & data.keys(): data[key]=[self.store.attachment(v) for v in array(data[key])]
        for key in ('equipment','accessories'):
            if key in data:data[key]=array(data[key])
        if 'accessories' in data:data['accessories']=[v if isinstance(v,dict) else {'name':str(v),'quantity':1} for v in data['accessories']]
        return data
    def resources(self,include_deleted=False):
        result=[]
        for kind,(name,pk,label,deleted,fields) in ASSETS.items():
            for row in self.rows(name):
                if row[deleted] and not include_deleted:continue
                result.append({**self.decode_fields(row,fields),'id':resource_id(kind,row[pk]),'kind':kind,
                    'label':row[label] or f'{kind}-{row[pk]}','deleted':bool(row[deleted])})
        fixed=[]
        for floor,area,unit in ROOMS:
            label=unit if re.fullmatch(r'\d-\d',unit) else area
            fixed.append(room(label,floor,area,unit))
        seen={r['label'] for r in fixed}
        table=self.t['formio_responses']
        for value in self.c.execute(select(table.c.place).where(table.c.form_id.like('_____D%')).distinct()).scalars():
            for label in room_labels(value):
                if label not in seen: fixed.append(room(label));seen.add(label)
        return result+fixed
    def resource(self,rid,include_deleted=False):
        result=next((r for r in self.resources(include_deleted) if r['id']==rid),None)
        if not result:fail('找不到資產',404)
        return result
    def encode_fields(self,data,fields):
        values={}
        for key,col in fields.items():
            if key not in data:continue
            value=data[key]
            if key in FILE_KEYS:
                value=[{**f,'uuid':str(f.get('id') or f.get('uuid')),'type':f.get('mime') or f.get('type','')} if isinstance(f,dict) else f for f in array(value)]
            if isinstance(value,(list,dict)):value=dump(value)
            if key in ('fix_date','valid_period') and not value:value=None
            values[col]=value
        return values
    def save_resource(self,body,rid=None):
        kind=body['kind'];data=clean(body['data']);label=body.get('label','').strip()
        if kind not in ASSETS:fail('無效資產類型')
        required=['model','owner','purchase_date','amount','passengers'] if kind=='vehicle' else ['name','location']
        for key in required:
            if data.get(key) in ('',None):fail('請填寫必要欄位：'+key)
        for key in ('amount','passengers','quantity','estimated_amount'):
            if data.get(key) not in ('',None):
                try:valid=math.isfinite(float(data[key])) and float(data[key])>=0
                except (ValueError,TypeError):valid=False
                if not valid:fail(key+' 必須為非負數')
        if kind=='vehicle':
            if not label:fail('請填寫車牌')
            parse(data['purchase_date'])
        elif data.get('state','列管') not in ('列管','不列管','停用'):fail('無效列管狀態')
        name,pk,labelcol,deleted,fields=ASSETS[kind];table=self.t[name]
        source_id=rid//10 if rid else None
        if rid and self.resource(rid)['kind']!=kind:fail('不可變更資產類型')
        label=label or 'EQ-'+uuid.uuid4().hex[:12]
        duplicate=self.c.execute(select(table.c[pk]).where(table.c[labelcol]==label)).scalars().all()
        if any(v!=source_id for v in duplicate):fail('車牌或編碼已存在',409)
        values=self.encode_fields(data,fields);values[labelcol]=label
        if rid:self.c.execute(update(table).where(table.c[pk]==source_id).values(**values))
        else:source_id=self.c.execute(insert(table).values(**values)).inserted_primary_key[0]
        return self.resource(resource_id(kind,source_id))
    def delete_resource(self,rid):
        r=self.resource(rid);kind=r['kind']
        if kind not in ASSETS:fail('固定作業區不可刪除')
        name,pk,_,deleted,_=ASSETS[kind]
        self.c.execute(update(self.t[name]).where(self.t[name].c[pk]==rid//10).values(**{deleted:1}))
    def records(self,rid):
        car=self.resource(rid,True);result=[]
        for index,(category,(name,fields)) in enumerate(RECORDS.items(),1):
            table=self.t[name]
            for row in self.rows(name,(table.c.plate==car['label']) & (func.coalesce(table.c.isdelete,0)==0)):
                result.append({**self.decode_fields(row,fields),'id':int(row['sn'])*10+index,'category':category,'created_at':iso(row['create_at'])})
        return sorted(result,key=lambda r:r['created_at'],reverse=True)
    def record_location(self,ident):
        index=ident%10
        if not 1<=index<=len(RECORDS):fail('無效紀錄',404)
        category=list(RECORDS)[index-1];name,fields=RECORDS[category];table=self.t[name]
        row=self.c.execute(select(table).where(table.c.sn==ident//10)).mappings().first()
        if not row or row['isdelete']:fail('找不到紀錄',404)
        return category,table,fields,row
    def save_record(self,rid,body,ident=None):
        category=body['category'];data=clean(body['data'])
        if category not in RECORDS:fail('無效紀錄類型')
        required={'insurance':['company','expiry'],'cost':['type','reason','amount'],'maintenance':['type','date'],'garage':[],'manager':['name']}[category]
        for key in required:
            if data.get(key) in (None,''):fail('請填寫必要欄位：'+key)
        if category=='insurance':parse(data['expiry'])
        if category=='maintenance':parse(data['date'])
        if category=='cost':
            try:valid=math.isfinite(float(data['amount'])) and float(data['amount'])>=0
            except (ValueError,TypeError):valid=False
            if not valid:fail('金額必須為非負數')
        name,fields=RECORDS[category];table=self.t[name];values=self.encode_fields(data,fields)
        if ident:
            oldcat,_,_,_=self.record_location(ident)
            if category!=oldcat:fail('不可變更紀錄類型')
            self.c.execute(update(table).where(table.c.sn==ident//10).values(**values))
        else:
            car=self.resource(rid)
            if car['kind']!='vehicle':fail('請選擇車輛')
            values['plate']=car['label']
            if category=='maintenance':values['data_type']='maintenance'
            pk=self.c.execute(insert(table).values(**values)).inserted_primary_key[0]
            ident=pk*10+list(RECORDS).index(category)+1
        return {'id':ident}
    def delete_record(self,ident):
        _,table,_,_=self.record_location(ident)
        self.c.execute(update(table).where(table.c.sn==ident//10).values(isdelete=1))
    def legacy_content(self,raw,rows,resources):
        # SQL provides the current slots; the legacy JSON provides complete fields.
        content=copy.deepcopy(raw.get('_polimax_next',{}).get('content',{}))
        first=rows[0];kind=first['form_id'][5]
        requirement=raw.get('Requirement_select') or (first['reason'] or '').split(' - ')[0]
        reason=array(requirement)[0] if array(requirement) else ''
        content.setdefault('reason',reason)
        content.setdefault('title',raw.get('RequireOption_Memo') or first['reason'] or first['form_id'])
        content.setdefault('applicant',raw.get('applicantID') or (raw.get('panel2') if kind=='D' else '') or first['applicant_ID'] or '')
        content.setdefault('application_date',raw.get('application_date') or iso(first['created_at'])[:10])
        employees=[]
        for row in rows:employees.extend(array(row['employees']))
        if not employees:employees=array(raw.get('usageTimeRegistration'))
        content['employees']=list(dict.fromkeys(str(v) for v in employees))
        content.setdefault('total_people',raw.get('total_people') or max(1,len(content['employees'])))
        details=[]
        config=FIELD_MAP['table'].get(reason,{})
        for detail in raw.get(config.get('grid_key',''),[]):
            if isinstance(detail,dict):details.append({'name':detail.get(FIELD_MAP['reason_detail_field_map'].get(reason,'')) or detail.get('exhibit_name2') or '',
                'city':detail.get(config.get('city_field',''),'') or '', 'district':detail.get(config.get('district_field',''),'') or ''})
        if not details:details=[{'name':(r['reason'] or '').partition(' - ')[2] or r['place'] or '', 'city':'','district':''} for r in rows]
        content.setdefault('details',details)
        content.setdefault('notes',raw.get('RequireOption_Memo',''))
        slots=[]
        for index,row in enumerate(rows):
            labels=room_labels(row['place']) if kind=='D' else [row['plate']]
            for label in labels:
                r=next((r for r in resources if r['label']==label and r['kind']=={'A':'vehicle','D':'room','E':'equipment'}[kind]),None)
                rid=r['id'] if r else room_id('historical:'+str(label))
                slots.append({'resource_id':rid,'start':iso(row['start']),'end':iso(row['end']),'detail_index':min(index,len(content['details'])-1)})
        content['slots']=slots
        content['resource_snapshots']=[r for r in resources if any(s['resource_id']==r['id'] for s in slots)]
        return content
    def bookings(self,include_deleted=False):
        table=self.t['formio_responses'];grouped=defaultdict(list)
        for row in self.rows('formio_responses'):
            if not re.fullmatch(r'\d{5}[ADE]\d{4,}',row['form_id'] or ''):continue
            grouped[row['form_id']].append(dict(row))
        flows=defaultdict(list)
        for row in self.rows('form_flows'):flows[row['form_id']].append(dict(row))
        resources=self.resources(True);result=[]
        for fid,allrows in grouped.items():
            active=[r for r in allrows if not r['is_deleted']]
            if not active and not include_deleted:continue
            rows=active or allrows;raw=self.raw(fid);meta=raw.get('_polimax_next',{})
            latest=max(flows[fid],key=lambda r:r['id'],default={});first=rows[0]
            status=latest.get('status') or 'PENDING'
            status={'lending':'PENDING','returned':'RETURN_ARRIVED'}.get(status,status)
            content=self.legacy_content(raw,rows,resources)
            result.append({'id':fid,'kind':fid[5],'owner':first['applicant_ID'] or '', 'content':content,'slots':content['slots'] if active else [],
                'status':status,'revision':fingerprint([allrows,flows[fid],raw]),'previous_id':meta.get('previous_id'),
                'parent_id':None,'deleted':not bool(active),'contact_person':latest.get('contact_person') or ','.join(content['employees']),
                'created_at':iso(first['created_at']),'updated_at':iso(latest.get('updated_at') or first['updated_at'])})
        return sorted(result,key=lambda r:r['created_at'],reverse=True)
    def booking(self,fid,deleted=False):
        self.store.path(fid)
        result=next((r for r in self.bookings(deleted) if r['id']==fid),None)
        if not result:fail('找不到有效申請',404)
        return result
    def number(self,kind):
        t=now();prefix=f'{t.year-1911}{t.month:02}{kind}'
        table=self.t['formio_responses']
        ids=list(self.c.execute(select(table.c.form_id).where(table.c.form_id.like(prefix+'%'))).scalars())
        folder=self.store.responses/FOLDERS[kind]
        ids.extend(p.stem for p in folder.glob(prefix+'*.json') if '.bak.' not in p.name)
        ids.extend(p.stem for p in self.pending if p.stem.startswith(prefix))
        maximum=max((int(v[len(prefix):]) for v in ids if re.fullmatch(re.escape(prefix)+r'\d+',v)),default=0)
        return prefix+f'{maximum+1:04}'
    def validate_booking(self,body,exclude=None):
        kind=body['kind'];content=clean(body['content'])
        if kind not in ('A','D','E'):fail('無效預約類型')
        slots=content.get('slots');details=content.get('details',[])
        if not isinstance(slots,list) or not slots or any(not isinstance(s,dict) for s in slots):fail('請新增有效預約時段')
        if not isinstance(details,list) or any(not isinstance(d,dict) for d in details):fail('明細格式錯誤')
        if kind=='D':content.update(reason='工作間租用',title=content.get('title') or '工作間租用')
        if not str(content.get('title','')).strip():fail('請填寫申請緣由')
        employees=content.get('employees',[])
        if not isinstance(employees,list) or any(not isinstance(e,str) for e in employees):fail('使用人員格式錯誤')
        if kind in ('A','E'):
            if content.get('reason') not in (REASONS if kind=='A' else E_REASONS):fail('請選擇使用需求')
            if not employees or not details:fail('請填寫使用人員與需求明細')
            for detail in details:
                if not str(detail.get('name','')).strip() and not (kind=='A' and content['reason']=='材料送貨'):fail('請填寫需求明細')
                if kind=='A' and not detail.get('city'):fail('請填寫明細縣市')
        if kind=='A':
            try:valid=int(content.get('total_people',0))>0
            except (ValueError,TypeError):valid=False
            if not valid:fail('使用人數至少為 1')
            if len(details) not in (1,len(slots)):fail('明細與時段須一對一，或一筆明細對應多個時段')
        selected=[];resources=self.resources()
        for index,slot in enumerate(slots):
            try:rid=int(slot['resource_id'])
            except (KeyError,ValueError,TypeError):fail('請選擇有效資源')
            r=next((r for r in resources if r['id']==rid),None)
            if not r or r['kind']!={'A':'vehicle','D':'room','E':'equipment'}[kind] or r.get('state')=='停用':fail('資源已刪除、停用或類型不符')
            start,end=parse(slot.get('start')),parse(slot.get('end'))
            if start>end or (kind!='A' and start==end):fail('結束時間必須晚於開始時間')
            if any(r['id']==prev[0]['id'] and start<=prev[2] and end>=prev[1] for prev in selected):fail('本張申請時段重疊（包含相接邊界）',409)
            table=self.t['formio_responses']
            q=select(table).where(func.coalesce(table.c.is_deleted,0)==0,table.c.start<=end,table.c.end>=start)
            if exclude:q=q.where(table.c.form_id!=exclude)
            if kind!='D':q=q.where(table.c.plate==r['label'])
            else:q=q.where(table.c.form_id.like('_____D%'))
            for row in self.c.execute(q.with_for_update()).mappings():
                if kind!='D' or r['label'] in room_labels(row['place']):fail(f"{r['label']} 與 {row['form_id']} 時段衝突（含相接邊界）",409)
            selected.append((r,start,end))
        content['slots']=[{'resource_id':r['id'],'start':iso(s),'end':iso(e),'detail_index':slots[i].get('detail_index',min(i,max(0,len(details)-1)))} for i,(r,s,e) in enumerate(selected)]
        content['resource_snapshots']=[r for r,_,_ in selected]
        return content,selected
    def encode_booking(self,fid,content,old=None):
        kind=fid[5];raw=copy.deepcopy(old or {})
        raw.update(Form_Type=FOLDERS[kind],form_id=fid,applicantID=content.get('applicant',''),application_date=content.get('application_date',''),
            usageTimeRegistration=content.get('employees',[]),total_people=content.get('total_people',1),RequireOption_Memo=content.get('notes',''))
        if kind=='A':
            reason=content['reason'];config=FIELD_MAP['table'][reason]
            raw['Requirement_select']=reason;grids=[];times=[]
            for detail in content['details']:
                grid={config['city_field']:detail.get('city',''),config['district_field']:detail.get('district','')}
                grid[FIELD_MAP['reason_detail_field_map'].get(reason,'exhibit_name2')]=detail.get('name','')
                grid[FIELD_MAP['employee_field_map'].get(reason,'employees')]=content.get('employees',[]);grids.append(grid)
            for slot in content['slots']:
                resource=self.resource(slot['resource_id'],True)
                times.append({config['plate_field']:resource['label'],config['start_field']:slot['start'],config['end_field']:slot['end']})
            raw[config['grid_key']]=grids;raw[config['time_key']]=times
        elif kind=='D':
            chosen=[self.resource(s['resource_id']) for s in content['slots']]
            raw.update(panel2=content.get('applicant',''),panel3=content['slots'][0]['start'],panel6=content['slots'][0]['end'],
                panelTable2={'1F':any(r.get('floor')=='1F' for r in chosen),'2F':any(r.get('floor')=='2F' for r in chosen)},
                panel4=[r['label'] for r in chosen if r.get('floor')!='2F'],panelTable2F=[r['label'] for r in chosen if r.get('floor')=='2F'])
        raw['_polimax_next']={**raw.get('_polimax_next',{}),'content':content}
        return raw
    def save_booking(self,body,user,fid=None):
        old=self.booking(fid) if fid else None
        if old:
            if old['kind']!=body['kind']:fail('不可變更表單類型')
            if body.get('revision')!=old['revision']:fail('資料已更新，請重新載入',409)
            if old['kind']=='A' and old['status']!='PENDING':fail('已發車不可重新安排預約',409)
        content,selected=self.validate_booking(body,fid)
        content.update(applicant=old['content']['applicant'] if old else user['name'],application_date=old['content']['application_date'] if old else now().date().isoformat())
        target=fid if old and body['kind']!='A' else self.number(body['kind'])
        table=self.t['formio_responses']
        if old:self.c.execute(update(table).where(table.c.form_id==fid).values(is_deleted=1))
        raw=self.encode_booking(target,content,self.raw(fid) if old else None)
        if old and target!=fid:raw['_polimax_next']['previous_id']=fid
        for index,(r,start,end) in enumerate(selected):
            details=content.get('details') or [{}];detail=details[min(content['slots'][index]['detail_index'],len(details)-1)]
            reason=content['reason']+(' - '+detail.get('name','') if body['kind']=='A' and detail.get('name') else '')
            place=r['label'] if body['kind']=='D' else detail.get('city','')+detail.get('district','')
            self.c.execute(insert(table).values(form_id=target,reason=reason,place=place,start=start,end=end,
                plate=r['label'] if body['kind']!='D' else '',employees=','.join(content.get('employees',[])),applicant_ID=old['owner'] if old else user['id'],is_deleted=0))
        if body['kind']=='A':
            self.c.execute(insert(self.t['form_flows']).values(form_id=target,status='PENDING',contact_person=','.join(content.get('employees',[])),created_at=now(),updated_at=now()))
        self.save_json(target,raw)
        return self.booking(target)
    def delete_booking(self,fid):
        self.booking(fid);table=self.t['formio_responses']
        self.c.execute(update(table).where(table.c.form_id==fid).values(is_deleted=1))
    def employees(self):
        result=set()
        for value in self.c.execute(select(self.t['formio_responses'].c.employees)).scalars():result.update(str(v) for v in array(value))
        for r in self.resources():
            for key in ('holder','owner','contact_person'):
                if r.get(key):result.add(str(r[key]))
        return sorted(result)
    def stage(self,fid):
        kind=fid[5] if len(fid)>5 else ''
        if kind not in ('B','C'):fail('不是出回程表單',404)
        raw=self.raw(fid)
        if not raw or raw.get('is_deleted') or raw.get('_polimax_next',{}).get('deleted'):fail('找不到出回程紀錄',404)
        meta=raw.get('_polimax_next',{});content=copy.deepcopy(meta.get('content',{}))
        start=content.setdefault('start',{})
        for key,col in STAGE_FIELDS[kind].items():
            if col in raw:
                value=raw[col]
                if key in ('tires','interior','exterior','equipment') and value=='異狀備註':value='異狀'
                start[key]=array(value) if key=='employees' else [self.store.attachment(v) for v in array(value)] if key.endswith('_files') else value
        start.setdefault('checks',[name for name,col in STAGE_CHECKS[kind].items() if raw.get(col)])
        if raw.get('page1Text') not in ('',None):
            arrival=content.setdefault('arrival',{})
            arrival.update(mileage=raw['page1Text'],confirmed=bool(raw.get('page2')))
            arrival['anomalies']=[label for code,label in [('repair','維修'),('violation','違規'),('accident','事故')] if raw.get('page1SelectBoxes',{}).get(code)]
        parent=raw.get('parent_form_id')
        if parent:
            booking=self.booking(parent,True)
            matching=next((r for r in booking['content'].get('resource_snapshots',[]) if r['label']==start.get('plate')),None)
            if matching:start['resource_id']=matching['id']
            start.setdefault('reservation_start',next((s['start'] for s in booking['slots'] if s['resource_id']==start.get('resource_id')),''))
        path=self.store.path(fid)
        stamp=iso(datetime.fromtimestamp(path.stat().st_mtime,TZ).replace(tzinfo=None)) if path.exists() else iso(now())
        return {'id':fid,'kind':kind,'parent_id':parent,'owner':raw.get('submitted_by') or raw.get('applicantID',''),
            'status':'PENDING','revision':fingerprint(raw),'content':content,'slots':[],
            'created_at':raw.get('submission_timestamp') or start.get('submitted_at') or stamp,'updated_at':stamp,
            'previous_id':None,'versions':[]}
    def stages(self,kind=None,parent=None):
        result=[]
        for k in (kind,) if kind else ('B','C'):
            if k not in ('B','C'):fail('無效階段類型')
            ids={p.stem for p in (self.store.responses/FOLDERS[k]).glob('*.json') if re.fullmatch(r'\d{5}'+k+r'\d{4,}',p.stem)}
            ids.update(p.stem for p in self.pending if p.parent.name==FOLDERS[k])
            for fid in sorted(ids):
                raw=self.raw(fid)
                if parent and raw.get('parent_form_id')!=parent:continue
                if raw.get('is_deleted') or raw.get('_polimax_next',{}).get('deleted'):continue
                try:result.append(self.stage(fid))
                except HTTPException as exc:
                    if exc.status_code!=404:raise
        return result
    def validate_stage(self,parent,kind,part,data):
        try:valid=math.isfinite(float(data['mileage'])) and 0<=float(data['mileage'])<1e9
        except (KeyError,ValueError,TypeError):valid=False
        if not valid or data.get('confirmed') is not True:fail('請填寫並確認有效里程')
        if part=='start':
            if not data.get('driver') or not str(data.get('place','')).strip():fail('請填寫駕駛與發車地點')
            employees=data.get('employees',[])
            if not isinstance(employees,list) or not employees:fail('請填寫使用人員')
            if len(set(employees+[data['driver']]))>=2 and not data.get('codriver'):fail('兩人以上須指定副駕')
            if data.get('driver')==data.get('codriver'):fail('駕駛與副駕不可相同')
            if any(not isinstance(n,str) or not n.strip() or len(n)>100 for n in employees+[data['driver']]+([data['codriver']] if data.get('codriver') else [])):fail('請填寫有效人員姓名')
            missing=set(CHECKS_B if kind=='B' else CHECKS_C)-set(data.get('checks',[]))
            if missing:fail('請完成車輛檢查：'+'、'.join(sorted(missing)))
            for key in ('tires','interior','exterior','equipment') if kind=='B' else ('exterior','equipment'):
                if data.get(key) not in ('正常','異狀'):fail('請填寫 '+key+' 檢查狀況')
                if data[key]=='異狀' and not str(data.get(key+'_note','')).strip():fail('請填寫異狀說明')
            ids={s['resource_id'] for s in parent['slots']}
            rid=data.get('resource_id')
            if rid is None and len(ids)==1:rid=next(iter(ids))
            if rid not in ids:fail('請選擇這張申請的車輛')
            data.update(resource_id=rid,plate=self.resource(rid,True)['label'],reservation_start=next(s['start'] for s in parent['slots'] if s['resource_id']==rid))
        elif any(v not in ('維修','違規','事故') for v in data.get('anomalies',[])):fail('無效異常類型')
    def save_stage_json(self,fid,parent,content,user):
        raw=self.raw(fid)
        raw.update(Form_Type=FOLDERS[fid[5]],form_id=fid,parent_form_id=parent['id'],submitted_by=user['id'])
        raw.setdefault('submission_timestamp',iso(now()))
        for key,col in STAGE_FIELDS[fid[5]].items():
            if key in content['start']:
                value=content['start'][key]
                if key in ('tires','interior','exterior','equipment') and value=='異狀':value='異狀備註'
                if key.endswith('_files'):
                    value=[{**f,'storage':'url','url':os.getenv('AMS_LEGACY_FILE_URL','https://uclerpnext.54ucl.com:3000').rstrip('/')+'/preview/'+f['id'],'data':{'uuid':f['id']}} for f in value]
                raw[col]=value
        for label,col in STAGE_CHECKS[fid[5]].items():raw[col]=label in content['start'].get('checks',[])
        if 'arrival' in content:
            arrival=content['arrival'];raw.update(page1Text=arrival['mileage'],page2=arrival['confirmed'],
                page1SelectBoxes={code:label in arrival.get('anomalies',[]) for code,label in [('repair','維修'),('violation','違規'),('accident','事故')]})
        raw['_polimax_next']={**raw.get('_polimax_next',{}),'content':content}
        self.save_json(fid,raw)
    def advance(self,fid,body,user):
        parent=self.booking(fid)
        if parent['kind']!='A' or parent['status'] not in STATES[:-1]:fail('沒有可執行的下一階段',409)
        if body.get('expected_status')!=parent['status'] or body.get('revision')!=parent['revision']:fail('流程已更新，請重新載入',409)
        index=STATES.index(parent['status']);kind='B' if index<2 else 'C';part='start' if index%2==0 else 'arrival'
        data=clean(copy.deepcopy(body['content']));self.validate_stage(parent,kind,part,data)
        existing=self.stages(kind,parent=fid)
        if part=='start':
            if existing:fail('此階段已存在',409)
            if kind=='C' and not self.stages('B',parent=fid):fail('缺少發車紀錄',409)
            stage_id=self.number(kind);content={}
        else:
            if not existing:fail('缺少出回程紀錄',409)
            stage=existing[-1];stage_id=stage['id'];content=stage['content']
            if float(data['mileage'])<float(content['start'].get('mileage',0)):fail('抵達里程不可小於出發里程')
        data['submitted_at']=iso(now());content[part]=data
        self.save_stage_json(stage_id,parent,content,user)
        table=self.t['form_flows'];row=self.c.execute(select(table.c.id).where(table.c.form_id==fid).order_by(table.c.id.desc()).limit(1)).first()
        if row:self.c.execute(update(table).where(table.c.id==row[0]).values(status=STATES[index+1],updated_at=now()))
        else:self.c.execute(insert(table).values(form_id=fid,status=STATES[index+1],created_at=now(),updated_at=now()))
        return self.booking(fid)
    def edit_stage(self,fid,body,user):
        stage=self.stage(fid)
        if body.get('revision')!=stage['revision']:fail('資料已更新，請重新載入',409)
        parent=self.booking(stage['parent_id'],True);content=copy.deepcopy(stage['content'])
        if set(body['content'])-set(content):fail('請由下一階段入口新增抵達內容')
        for part,change in body['content'].items():
            previous=content[part];value={**previous,**change};self.validate_stage(parent,stage['kind'],part,value)
            for key in ('submitted_at','resource_id','plate','reservation_start'):
                if key in previous and value.get(key)!=previous[key]:fail(key+' 不可修改')
            content[part]=value
        if 'arrival' in content and float(content['arrival']['mileage'])<float(content['start']['mileage']):fail('抵達里程不可小於出發里程')
        self.save_stage_json(fid,parent,content,user);return self.stage(fid)
    def detail(self,fid):
        booking=self.booking(fid);stages=self.stages(parent=fid)
        required=[('B',False)]*(booking['status']!='PENDING')+[('B',True)]*(booking['status'] in STATES[2:])+[('C',False)]*(booking['status'] in STATES[3:])+[('C',True)]*(booking['status']==STATES[4])
        booking.update(stages=stages,versions=[],history=[],incomplete=any(not any(s['kind']==kind and (not arrival or 'arrival' in s['content']) for s in stages) for kind,arrival in required))
        for stage in stages:
            for part,data in stage['content'].items():
                booking['history'].append({'action':stage['id']+' '+('出發' if part=='start' else '抵達'),'actor':data.get('driver',''),'time':data.get('submitted_at') or stage['updated_at']})
        if booking.get('previous_id'):
            try:booking['previous_version']=self.booking(booking['previous_id'],True)
            except HTTPException:pass
        for path in sorted(self.store.path(fid).parent.glob(fid+'_*.bak.json'),reverse=True):
            try:
                value=json.loads(path.read_text());raw=value.get('content',value)
                content=raw.get('_polimax_next',{}).get('content',{})
                booking['versions'].append({'id':fingerprint(path.name),'actor':raw.get('submitted_by',''),'time':iso(datetime.fromtimestamp(path.stat().st_mtime,TZ).replace(tzinfo=None)),'data':{'content':content}})
            except (ValueError,OSError):continue
        return booking

STAGE_FIELDS={
 'B':{'submitted_at':'panel2','plate':'panel6','driver':'panelTable11Text2','codriver':'panelTable111','place':'panel3','employees':'panel4',
      'mileage':'panelTableText','confirmed':'panelTable9','notes':'panelPanelPanelTextArea','tires':'panelTableRadio4','interior':'panelTableRadio','exterior':'panelTableRadio2','equipment':'panelTableRadio3',
      'tires_note':'panelTable13','interior_note':'panelTable12','exterior_note':'panelTable10','equipment_note':'panelTableTextArea2'},
 'C':{'submitted_at':'page4','plate':'page7','driver':'page1Table4','codriver':'page1Table1','place':'page5','employees':'page8',
      'mileage':'page2Table8Text','confirmed':'page2Table9','notes':'page2PanelTextArea','exterior':'page2TableRadio','equipment':'page2TableRadio2',
      'interior_files':'page2TableFile','exterior_files':'page2Table8','equipment_files':'page2Table10','parking_files':'page2PanelFile'},
}
STAGE_CHECKS={'B':dict(zip(CHECKS_B,['panelTable2','panelTable3','panelTable5','panelTable4','panelTable6','panelTable7','panelTable8'])),
 'C':dict(zip(CHECKS_C,['page2Table2','page2Table3','page2Table4','page2Table5','page2Table6','page2Table7']))}
