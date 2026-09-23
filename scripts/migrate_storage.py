"""One-time copy into standalone storage; never writes SQL or removes source files."""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from settings import data_path, settings

IDENT = re.compile(r'^[a-zA-Z0-9_-]{1,100}$')

def copy_verified(source, target):
    content = source.read_bytes()
    if target.exists():
        if target.read_bytes() != content:
            raise RuntimeError('Destination differs: ' + str(target))
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as out:
        os.chmod(target, 0o600)
        out.write(content)
    if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(content).digest():
        raise RuntimeError('Copy verification failed')
    return True

def references(value, found, attachment=False):
    if isinstance(value, list):
        for item in value: references(item, found, attachment)
    elif isinstance(value, dict):
        ident = value.get('uuid') or value.get('file_uuid')
        if not ident and isinstance(value.get('data'), dict): ident = value['data'].get('uuid')
        if not ident and attachment: ident = value.get('id')
        if isinstance(ident, str) and IDENT.fullmatch(ident):
            found.setdefault(ident, {'name': value.get('originalName') or value.get('name') or ident,
                                      'mime': value.get('mime') or value.get('type') or ''})
        for key, item in value.items():
            references(item, found, key in ('attachments','files') or 'file' in key.lower() or 'uuid' in key.lower())
    elif isinstance(value, str) and value:
        try:
            parsed=json.loads(value)
            if isinstance(parsed,(dict,list)):
                references(parsed,found,attachment);return
        except (ValueError,TypeError): pass
        match=re.search(r'/(?:file|preview)/([a-zA-Z0-9_-]{1,100})(?:[/?#]|$)', value)
        if match: found.setdefault(match[1], {'name':match[1], 'mime':''})
        elif attachment and IDENT.fullmatch(value): found.setdefault(value, {'name':value,'mime':''})

def database_references(found):
    from database import configuration
    from sqlalchemy import create_engine, inspect, text
    _, url, mysql = configuration(ROOT)
    if url.get_backend_name() != 'mysql': raise RuntimeError('Migration requires MySQL mode')
    engine=create_engine(url,hide_parameters=True,connect_args={'connect_timeout':10})
    try:
        with engine.connect() as c:
            c.exec_driver_sql('START TRANSACTION READ ONLY')
            inspector=inspect(c)
            # Only attachment-bearing tables, no arbitrary table or sensitive key exports.
            for table in ('CarList','EquipmentList','insurance_records','cost','vehicle_records','garage_files','vehicle_managers'):
                if not inspector.has_table(table): continue
                columns=[col['name'] for col in inspector.get_columns(table) if any(k in col['name'].lower() for k in ('uuid','file','attachment'))]
                if not columns: continue
                query='SELECT '+','.join('`'+col+'`' for col in columns)+' FROM `'+table+'`'
                for row in c.exec_driver_sql(query):
                    for value in row: references(value,found,True)
            c.rollback()
    finally: engine.dispose()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Old project directory, used only during migration')
    parser.add_argument('--file-url', help='Old file service base URL, used only for this download')
    parser.add_argument('--scan-database', action='store_true', help='Read attachment references from current MySQL')
    parser.add_argument('--download', action='store_true', help='Download referenced files; requires --file-url')
    args=parser.parse_args()
    if args.download and (not args.file_url or urlsplit(args.file_url).scheme not in ('http','https')):
        parser.error('--download requires an http(s) --file-url')
    data=data_path(ROOT);data.mkdir(parents=True,exist_ok=True)
    source=args.source.resolve();forms=source/'回應'
    if not forms.is_dir(): raise RuntimeError('Source responses directory missing')
    copied=0;found={}
    for path in sorted(forms.rglob('*')):
        if path.is_symlink(): raise RuntimeError('Source symlink requires explicit resolution: '+str(path))
        if not path.is_file(): continue
        copied+=copy_verified(path,data/'responses'/path.relative_to(forms))
        if path.suffix=='.json': references(json.loads(path.read_text()),found)
    manifest=source/'mini-engine/data/snapshots/latest-AMS.json'
    meta=json.loads(manifest.read_text());snapshot=manifest.parent/Path(meta['file']).name
    payload=json.loads(snapshot.read_text())
    if 'data' not in payload or 'version' not in payload.get('meta',{}): raise RuntimeError('Invalid permission snapshot')
    copy_verified(snapshot,data/'permissions'/snapshot.name)
    # Localize the manifest reference; never retain an absolute path to the old checkout.
    target=data/'permissions/latest-AMS.json'
    normalized={**meta,'file':snapshot.name}
    if target.exists() and json.loads(target.read_text())!=normalized: raise RuntimeError('Existing permission manifest differs')
    if not target.exists():
        target.write_text(json.dumps(normalized,ensure_ascii=False,indent=2));target.chmod(0o600)
    if args.scan_database: database_references(found)
    files=data/'files';files.mkdir(exist_ok=True)
    missing=[];downloaded=0
    import httpx
    with httpx.Client(timeout=httpx.Timeout(30,connect=5),follow_redirects=True) as client:
        for ident,meta in sorted(found.items()):
            path=files/ident;index=files/(ident+'.json')
            if path.is_file() and index.is_file(): continue
            if not args.download:
                missing.append({'id':ident,'reason':'not_downloaded'});continue
            temporary=files/(ident+'.part')
            try:
                with client.stream('GET',args.file_url.rstrip('/')+'/file/'+ident) as response:
                    response.raise_for_status()
                    mime=response.headers.get('content-type','application/octet-stream').split(';')[0]
                    if mime=='text/html': raise ValueError('HTML response is not an attachment')
                    name=meta['name']
                    disposition=response.headers.get('content-disposition','')
                    match=re.search(r"filename\*=UTF-8''([^;]+)|filename=\"([^\"]+)\"",disposition,re.I)
                    if match: name=unquote(match[1] or match[2])
                    with temporary.open('xb') as out:
                        os.chmod(temporary,0o600)
                        for chunk in response.iter_bytes(): out.write(chunk)
                    if path.exists() and path.read_bytes()!=temporary.read_bytes(): raise ValueError('Existing attachment differs')
                    os.replace(temporary,path)
                    metadata={'id':ident,'uuid':ident,'name':Path(name).name,'mime':mime,'size':path.stat().st_size,'migrated':True}
                    index.write_text(json.dumps(metadata,ensure_ascii=False));index.chmod(0o600)
                    downloaded+=1
            except (httpx.HTTPError,ValueError,OSError) as exc:
                missing.append({'id':ident,'reason':type(exc).__name__})
                print('Attachment download failed: '+type(exc).__name__,flush=True)
            finally: temporary.unlink(missing_ok=True)
    report={'forms_copied':copied,'forms_total':sum(p.is_file() for p in forms.rglob('*')),
            'permission_version':payload['meta']['version'],'attachment_references':len(found),
            'attachments_downloaded':downloaded,'missing':missing,'complete':not missing}
    (data/'migration-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='missing'},ensure_ascii=False))
    if missing:
        print('Missing attachment details: .data/migration-report.json');return 2
    return 0

if __name__=='__main__':
    raise SystemExit(main())
