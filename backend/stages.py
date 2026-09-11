"""A shared workflow; B/C revisions retain both departure and arrival content."""
import json
import math
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

CHECKS_B=['擋風玻璃清潔','照後鏡清潔','油量檢查','輪胎檢查','車輛內部清潔','車體外部檢查','隨車設備檢查']
CHECKS_C=['車輛內部清潔','車輛內部物品歸位','車輛鑰匙歸位','油量檢查','車體外部檢查','隨車設備檢查']

def validate_stage(db,parent,kind,part,data):
    try:
        mileage=float(data['mileage'])
        if not math.isfinite(mileage) or not 0<=mileage<1e9:raise ValueError()
    except (KeyError,ValueError,TypeError):raise HTTPException(422,'請填寫有效的非負里程')
    if data.get('confirmed') is not True:raise HTTPException(422,'請確認里程')
    if part=='start':
        if not data.get('driver') or not str(data.get('place','')).strip():raise HTTPException(422,'請填寫駕駛與發車地點')
        employees=data.get('employees',[])
        if not isinstance(employees,list) or not employees:raise HTTPException(422,'請填寫使用人員')
        if len(set(employees+[data['driver']]))>=2 and not data.get('codriver'):raise HTTPException(422,'兩人以上須指定副駕')
        if data.get('codriver')==data['driver']:raise HTTPException(422,'駕駛與副駕不可相同')
        if any(not isinstance(n,str) or not n.strip() or len(n)>100 for n in employees+[data['driver']]+([data['codriver']] if data.get('codriver') else [])):raise HTTPException(422,'請填寫有效人員姓名')
        missing=set(CHECKS_B if kind=='B' else CHECKS_C)-set(data.get('checks',[]))
        if missing:raise HTTPException(422,'請完成檢查：'+'、'.join(sorted(missing)))
        for key in (['tires','interior','exterior','equipment'] if kind=='B' else ['exterior','equipment']):
            if data.get(key) not in ('正常','異狀'):raise HTTPException(422,f'請選擇 {key} 檢查狀況')
            if data.get(key)=='異狀' and not str(data.get(key+'_note','')).strip():raise HTTPException(422,f'請填寫 {key} 異狀說明')
        slots=db.scalars(select(Occupancy).where(Occupancy.form_id==parent.id)).all()
        ids={s.resource_id for s in slots}
        rid=data.get('resource_id')
        if rid is None and len(ids)==1:rid=next(iter(ids))
        if rid not in ids:raise HTTPException(422,'請選擇此申請內的車輛，多車申請共用同一流程')
        r=db.get(Resource,rid)
        data['resource_id']=rid
        data['plate']=r.label if r else data.get('plate','歷史車輛')
        data['reservation_start']=iso(next(s.start for s in slots if s.resource_id==rid))
    else:
        if any(a not in ('維修','違規','事故') for a in data.get('anomalies',[])):raise HTTPException(422,'無效的途中異常類型')
    for key in ('interior_files','exterior_files','equipment_files','parking_files'):
        for file in data.get(key,[]):
            a=db.get(Attachment,file.get('id'))
            if not a or not a.mime.startswith('image/') or a.size>1024**3:raise HTTPException(422,'階段照片須為已上傳圖片且不超過 1 GB')

class EditStage(BaseModel):
    revision:int
    content:dict


def install(ctx):
    for name in ('app','Form','Resource','Occupancy','Attachment','Sequence','getdb','user','writer','admin','getform','form_json','snapshot','event','now','iso','dump','USERS','employee_names'):
        globals()[name]=ctx[name]
    ctx['validate_stage']=validate_stage
    @app.get('/api/stages')
    def stages(kind:str='B',u=Depends(user),db=Depends(getdb)):
        if kind not in ('B','C'):raise HTTPException(422,'請選擇 B 或 C')
        return [form_json(f,db) for f in db.scalars(select(Form).where(Form.kind==kind,Form.deleted==0).order_by(Form.created_at.desc()))]
    @app.get('/api/stages/{id}')
    def detail(id:str,u=Depends(user),db=Depends(getdb)):
        f=getform(db,id)
        if f.kind not in ('B','C'):raise HTTPException(404,'不是階段表')
        result=form_json(f,db)
        result['versions']=[{'id':v.id,'actor':v.actor,'time':iso(v.created_at),'data':json.loads(v.payload)} for v in db.scalars(select(ctx['Revision']).where(ctx['Revision'].form_id==id))]
        return result
    @app.put('/api/stages/{id}')
    def edit(id:str,body:EditStage,u=Depends(writer),db=Depends(getdb)):
        db.execute(select(Sequence).where(Sequence.key=='global').with_for_update()).scalar_one()
        f=getform(db,id)
        if f.kind not in ('B','C'):raise HTTPException(422,'不是階段表')
        if f.revision!=body.revision:raise HTTPException(409,'資料已更新，請重新載入')
        parent=db.get(Form,f.parent_id)
        if not parent:raise HTTPException(409,'缺少父申請')
        original=json.loads(f.payload)
        merged={**original,**body.content}
        if set(merged)-set(original):raise HTTPException(422,'請由下一階段入口新增抵達內容')
        for part in original:
            if part not in ('start','arrival'):continue
            data={**original[part],**body.content.get(part,{})}
            validate_stage(db,parent,f.kind,part,data)
            for key in ('submitted_at','resource_id','plate','reservation_start'):
                if key in original[part] and data.get(key)!=original[part][key]:raise HTTPException(422,f'{key} 不可修改')
            merged[part]=data
        if merged.get('arrival') and float(merged['arrival']['mileage'])<float(merged['start']['mileage']):raise HTTPException(422,'結束里程不得小於開始里程')
        snapshot(db,f,u);f.payload=dump(merged);f.revision+=1;f.updated_at=now()
        event(db,parent,'修正 '+f.id+'（流程狀態保持 '+parent.status+'）',u)
        db.commit();return form_json(f,db)
    @app.delete('/api/stages/{id}')
    def delete(id:str,u=Depends(user),db=Depends(getdb)):
        db.execute(select(Sequence).where(Sequence.key=='global').with_for_update()).scalar_one()
        f=getform(db,id)
        if f.kind not in ('B','C'):raise HTTPException(422,'不是階段表')
        snapshot(db,f,u);f.deleted=1
        parent=db.get(Form,f.parent_id)
        event(db,parent,'刪除 '+f.id+'，流程資料不完整',u)
        db.commit();return {'ok':True,'incomplete':True}
