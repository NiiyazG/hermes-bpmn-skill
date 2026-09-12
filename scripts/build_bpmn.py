#!/usr/bin/env python3
from pathlib import Path
import argparse, json, math, os, re, shutil, subprocess, sys, zipfile

try:
    from lxml import etree
    from PIL import Image
    import fitz
except Exception as e:
    print("Missing dependency:",e,file=sys.stderr)
    print("Install: python -m pip install lxml Pillow PyMuPDF",file=sys.stderr)
    sys.exit(2)

BPMN="http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI="http://www.omg.org/spec/BPMN/20100524/DI"
DC="http://www.omg.org/spec/DD/20100524/DC"
DI="http://www.omg.org/spec/DD/20100524/DI"
XSI="http://www.w3.org/2001/XMLSchema-instance"
NS={"bpmn":BPMN,"bpmndi":BPMNDI,"dc":DC,"di":DI,"xsi":XSI}

TYPE_MAP={
 "startEvent":"startEvent","endEvent":"endEvent","userTask":"userTask",
 "serviceTask":"serviceTask","manualTask":"manualTask","exclusiveGateway":"exclusiveGateway",
 "parallelGateway":"parallelGateway","subProcess":"subProcess"
}

def q(ns,tag): return etree.QName(ns,tag)
def txt_wrap(s,n=28):
    words=str(s).split(); out=[]; cur=""
    for w in words:
        if not cur: cur=w
        elif len(cur)+1+len(w)<=n: cur+=" "+w
        else: out.append(cur); cur=w
    if cur: out.append(cur)
    return out or [""]

def load_model(path):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("process","pools","nodes","flows"):
        if key not in data: raise ValueError(f"Missing required key: {key}")
    return data

def normalize(model):
    # pool/lane geometry
    style=model.setdefault("style",{})
    style.setdefault("lane_height",240)
    style.setdefault("pool_gap",80)
    style.setdefault("label_width",180)
    style.setdefault("margin_x",120)
    style.setdefault("margin_y",160)
    style.setdefault("node_gap",330)
    style.setdefault("task_width",250)
    style.setdefault("task_height",78)
    style.setdefault("gateway_size",66)
    style.setdefault("event_size",46)
    style.setdefault("font_size",13)
    
    pools=model["pools"]
    pool_map={p["id"]:p for p in pools}
    lane_pool={}
    for p in pools:
        for lane in p.get("lanes",[]): lane_pool[lane["id"]]=p["id"]
    nodes={n["id"]:n for n in model["nodes"]}
    # Validate lane ownership and assign auto positions by node order per pool.
    counters={p["id"]:0 for p in pools}
    pool_top={}
    y=style["margin_y"]
    for p in pools:
        pool_top[p["id"]]=y
        y += max(1,len(p.get("lanes",[])))*style["lane_height"] + style["pool_gap"]
    for n in model["nodes"]:
        if n["pool"] not in pool_map: raise ValueError(f"Node {n['id']} references missing pool")
        if n["lane"] not in lane_pool: raise ValueError(f"Node {n['id']} references missing lane")
        if lane_pool[n["lane"]]!=n["pool"]: raise ValueError(f"Node {n['id']} lane is in another pool")
        p=pool_map[n["pool"]]
        lane_ids=[l["id"] for l in p.get("lanes",[])]
        li=lane_ids.index(n["lane"])
        typ=n["type"]
        if typ in ("exclusiveGateway","parallelGateway"):
            w=h=style["gateway_size"]
        elif typ in ("startEvent","endEvent"):
            w=h=style["event_size"]
        else:
            w=n.get("width",style["task_width"]); h=n.get("height",style["task_height"])
        n.setdefault("width",w); n.setdefault("height",h)
        if "x" not in n:
            n["x"]=style["margin_x"]+style["label_width"]+80+counters[n["pool"]]*style["node_gap"]
            counters[n["pool"]]+=1
        if "y" not in n:
            n["y"]=pool_top[n["pool"]]+li*style["lane_height"]+(style["lane_height"]-h)/2
    return model,pool_top

def point(n,side="R",frac=.5):
    x,y,w,h=n["x"],n["y"],n["width"],n["height"]
    return {"L":(x,y+h*frac),"R":(x+w,y+h*frac),"T":(x+w*frac,y),"B":(x+w*frac,y+h)}[side]

def auto_waypoints(src,tgt,flow,pool_bounds):
    # Forward flows use right->left; backward flows use a corridor above the source pool.
    if flow.get("waypoints"): return [tuple(p) for p in flow["waypoints"]]
    same_pool=src["pool"]==tgt["pool"]
    if flow["type"]=="message" or not same_pool:
        a=point(src,"R"); b=point(tgt,"L"); mid=(a[0]+b[0])/2
        return [a,(mid,a[1]),(mid,b[1]),b]
    if tgt["x"] >= src["x"]+src["width"]-5:
        a=point(src,"R"); b=point(tgt,"L")
        if abs(a[1]-b[1])<1e-6: return [a,b]
        mid=(a[0]+b[0])/2
        return [a,(mid,a[1]),(mid,b[1]),b]
    # return loop: source top -> corridor -> target top
    a=point(src,"T"); b=point(tgt,"T")
    top=pool_bounds[src["pool"]][1]-35
    return [a,(a[0],top),(b[0],top),b]

def build(model,outdir):
    outdir=Path(outdir); outdir.mkdir(parents=True,exist_ok=True)
    model,pool_top=normalize(model)
    proc=model["process"]
    nodes={n["id"]:n for n in model["nodes"]}
    pools={p["id"]:p for p in model["pools"]}
    style=model["style"]
    # Canvas dimensions.
    maxx=max(n["x"]+n["width"] for n in nodes.values())+250
    maxy=0; pool_bounds={}
    for p in model["pools"]:
        h=max(1,len(p.get("lanes",[])))*style["lane_height"]
        pool_bounds[p["id"]]=(style["margin_x"],pool_top[p["id"]],maxx-style["margin_x"]*2,h)
        maxy=max(maxy,pool_top[p["id"]]+h)
    canvas_w=maxx; canvas_h=maxy+120
    # BPMN XML
    defs=etree.Element(q(BPMN,"definitions"),nsmap=NS,id="Definitions_1",targetNamespace="https://hermes.local/bpmn")
    process_elems={}
    for p in model["pools"]:
        pe=etree.SubElement(defs,q(BPMN,"process"),id=f"Process_{p['id']}",name=p["name"],isExecutable="false")
        process_elems[p["id"]]=pe
        ls=etree.SubElement(pe,q(BPMN,"laneSet"),id=f"LaneSet_{p['id']}")
        for lane in p.get("lanes",[]):
            le=etree.SubElement(ls,q(BPMN,"lane"),id=lane["id"],name=lane["name"])
            for n in model["nodes"]:
                if n["lane"]==lane["id"]:
                    etree.SubElement(le,q(BPMN,"flowNodeRef")).text=n["id"]
    incoming={nid:[] for nid in nodes}; outgoing={nid:[] for nid in nodes}
    for f in model["flows"]:
        if f["source"] not in nodes or f["target"] not in nodes: continue
        if f["type"]=="sequence":
            outgoing[f["source"]].append(f["id"]); incoming[f["target"]].append(f["id"])
    for n in model["nodes"]:
        pe=process_elems[n["pool"]]
        el=etree.SubElement(pe,q(BPMN,TYPE_MAP[n["type"]]),id=n["id"],name=n.get("name",n["id"]))
        if n.get("notes"): etree.SubElement(el,q(BPMN,"documentation")).text=n["notes"]
        for fid in incoming[n["id"]]: etree.SubElement(el,q(BPMN,"incoming")).text=fid
        for fid in outgoing[n["id"]]: etree.SubElement(el,q(BPMN,"outgoing")).text=fid
    # collaboration and flows
    collab=etree.SubElement(defs,q(BPMN,"collaboration"),id="Collaboration_1")
    for p in model["pools"]:
        etree.SubElement(collab,q(BPMN,"participant"),id=f"Participant_{p['id']}",name=p["name"],processRef=f"Process_{p['id']}")
    waypoints={}
    for f in model["flows"]:
        src,tgt=nodes[f["source"]],nodes[f["target"]]
        pts=auto_waypoints(src,tgt,f,pool_bounds); waypoints[f["id"]]=pts
        if f["type"]=="sequence":
            if src["pool"]!=tgt["pool"]:
                continue
            sf=etree.SubElement(process_elems[src["pool"]],q(BPMN,"sequenceFlow"),id=f["id"],sourceRef=f["source"],targetRef=f["target"])
            if f.get("name"): sf.set("name",f["name"])
        else:
            mf=etree.SubElement(collab,q(BPMN,"messageFlow"),id=f["id"],sourceRef=f["source"],targetRef=f["target"])
            if f.get("name"): mf.set("name",f["name"])
    # data objects and annotations (simple)
    for d in model.get("data_objects",[]):
        pe=process_elems[d["pool"]]
        objid=f"{d['id']}_obj"
        etree.SubElement(pe,q(BPMN,"dataObject"),id=objid,name=d["name"])
        etree.SubElement(pe,q(BPMN,"dataObjectReference"),id=d["id"],dataObjectRef=objid,name=d["name"])
    for a in model.get("annotations",[]):
        pe=process_elems[a["pool"]]
        an=etree.SubElement(pe,q(BPMN,"textAnnotation"),id=a["id"])
        etree.SubElement(an,q(BPMN,"text")).text=a["text"]
    # DI
    dia=etree.SubElement(defs,q(BPMNDI,"BPMNDiagram"),id="BPMNDiagram_1")
    plane=etree.SubElement(dia,q(BPMNDI,"BPMNPlane"),id="BPMNPlane_1",bpmnElement="Collaboration_1")
    def bounds_el(parent,x,y,w,h): etree.SubElement(parent,q(DC,"Bounds"),x=str(x),y=str(y),width=str(w),height=str(h))
    for p in model["pools"]:
        x,y,w,h=pool_bounds[p["id"]]
        sh=etree.SubElement(plane,q(BPMNDI,"BPMNShape"),id=f"Participant_{p['id']}_di",bpmnElement=f"Participant_{p['id']}",isHorizontal="true"); bounds_el(sh,x,y,w,h)
        lane_y=y
        for lane in p.get("lanes",[]):
            sh=etree.SubElement(plane,q(BPMNDI,"BPMNShape"),id=f"{lane['id']}_di",bpmnElement=lane["id"],isHorizontal="true"); bounds_el(sh,x,lane_y,w,style["lane_height"]); lane_y+=style["lane_height"]
    for n in model["nodes"]:
        sh=etree.SubElement(plane,q(BPMNDI,"BPMNShape"),id=f"{n['id']}_di",bpmnElement=n["id"]); bounds_el(sh,n["x"],n["y"],n["width"],n["height"])
    for f in model["flows"]:
        ed=etree.SubElement(plane,q(BPMNDI,"BPMNEdge"),id=f"{f['id']}_di",bpmnElement=f["id"])
        for x,y in waypoints[f["id"]]: etree.SubElement(ed,q(DI,"waypoint"),x=str(x),y=str(y))
    bpmn=outdir/'process.bpmn'; xml=outdir/'process.xml'
    raw=etree.tostring(defs,pretty_print=True,xml_declaration=True,encoding="UTF-8")
    bpmn.write_bytes(raw); xml.write_bytes(raw)
    (outdir/'process-model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2),encoding="utf-8")
    # SVG render
    svg=render_svg(model,pool_bounds,waypoints,canvas_w,canvas_h)
    svg_path=outdir/'process.svg'; svg_path.write_text(svg,encoding="utf-8")
    pdf=outdir/'process.pdf'; png=outdir/'process.png'
    svg_doc=fitz.open(stream=svg.encode('utf-8'),filetype='svg')
    pdf.write_bytes(svg_doc.convert_to_pdf())
    page=svg_doc[0]
    output_width=min(int(canvas_w*2),20000)
    scale=output_width/page.rect.width
    pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
    pix.save(str(png))
    img=Image.open(png).convert('RGB')
    img.save(outdir/'process.jpg',quality=94,optimize=True)
    img.save(outdir/'process.webp',quality=92,method=6)
    img.save(outdir/'process.tiff',compression='tiff_lzw')
    eps_status="SKIPPED"
    if shutil.which('inkscape'):
        r=subprocess.run(['inkscape',str(svg_path),'--export-filename='+str(outdir/'process.eps')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        eps_status='OK' if r.returncode==0 and (outdir/'process.eps').exists() else 'FAILED'
    # HTML
    (outdir/'process.html').write_text('<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#eef5f8}img{max-width:none}</style><img src="process.svg">',encoding='utf-8')
    # brief
    brief=build_brief(model)
    (outdir/'brief-description.md').write_text(brief,encoding='utf-8')
    # validation
    report,passed=validate(model,pool_bounds,waypoints,eps_status)
    (outdir/'validation-report.txt').write_text(report,encoding='utf-8')
    # zip
    zpath=outdir/'all-formats.zip'
    with zipfile.ZipFile(zpath,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(outdir.iterdir()):
            if p.is_file() and p.name!='all-formats.zip': z.write(p,arcname=p.name)
    return passed

def render_svg(model,pool_bounds,waypoints,W,H):
    from xml.sax.saxutils import escape
    nodes={n['id']:n for n in model['nodes']}; style=model['style']
    def text(x,y,lines,size=13,weight=500,anchor='middle',fill='#17364d'):
        if isinstance(lines,str): lines=[lines]
        spans=[]
        for i,line in enumerate(lines): spans.append(f'<tspan x="{x}" dy="{0 if i==0 else size*1.25}">{escape(str(line))}</tspan>')
        return f'<text x="{x}" y="{y}" font-family="Arial,DejaVu Sans,sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="{fill}">'+''.join(spans)+'</text>'
    s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       '<defs><marker id="arr" markerWidth="10" markerHeight="10" refX="10" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,5 L0,10 z" fill="#2479b8"/></marker><marker id="msg" markerWidth="10" markerHeight="10" refX="10" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,5 L0,10" fill="none" stroke="#5d8399" stroke-width="1.3"/></marker></defs>',f'<rect width="{W}" height="{H}" fill="#f8fbfd"/>']
    # pools/lanes
    for p in model['pools']:
        x,y,w,h=pool_bounds[p['id']]; s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff" stroke="#2479b8" stroke-width="1.4"/>')
        ly=y
        for lane in p.get('lanes',[]):
            s.append(f'<line x1="{x}" y1="{ly}" x2="{x+w}" y2="{ly}" stroke="#c8dce7"/>')
            s.append(text(x+10,ly+22,lane['name'],11,600,'start','#355b73'))
            ly+=style['lane_height']
    # flows behind nodes
    for f in model['flows']:
        pts=waypoints[f['id']]; d='M '+' L '.join(f'{x},{y}' for x,y in pts)
        if f['type']=='sequence':
            s.append(f'<path d="{d}" fill="none" stroke="#2479b8" stroke-width="2" stroke-linejoin="round" marker-end="url(#arr)"/>')
        else:
            s.append(f'<path d="{d}" fill="none" stroke="#5d8399" stroke-width="1.6" stroke-dasharray="7 6" marker-end="url(#msg)"/>')
        if f.get('name'):
            x,y=pts[1] if len(pts)>2 else ((pts[0][0]+pts[-1][0])/2,(pts[0][1]+pts[-1][1])/2)
            s.append(f'<rect x="{x-22}" y="{y-19}" width="44" height="20" rx="5" fill="#fff" stroke="#dceaf1"/>'); s.append(text(x,y-5,f['name'],11,700))
    # nodes on top
    for n in model['nodes']:
        x,y,w,h=n['x'],n['y'],n['width'],n['height']; typ=n['type']
        if typ in ('userTask','serviceTask','manualTask','subProcess'):
            s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#fff" stroke="#2479b8" stroke-width="1.8"/>')
            lines=txt_wrap(n['name'],max(18,int(w/10))); yy=y+h/2-(len(lines)-1)*7
            s.append(text(x+w/2,yy,lines,12,600))
        elif typ in ('exclusiveGateway','parallelGateway'):
            cx=x+w/2;cy=y+h/2; pts=f'{cx},{y} {x+w},{cy} {cx},{y+h} {x},{cy}'
            s.append(f'<polygon points="{pts}" fill="#fff" stroke="#2479b8" stroke-width="1.8"/>')
            d=10
            if typ=='exclusiveGateway': s.append(f'<path d="M{cx-d},{cy-d} L{cx+d},{cy+d} M{cx+d},{cy-d} L{cx-d},{cy+d}" stroke="#2479b8" stroke-width="1.8"/>')
            else: s.append(f'<path d="M{cx-d},{cy} L{cx+d},{cy} M{cx},{cy-d} L{cx},{cy+d}" stroke="#2479b8" stroke-width="1.8"/>')
            if n.get('name'): s.append(text(cx,y+h+18,txt_wrap(n['name'],28),10,600))
        else:
            cx=x+w/2;cy=y+h/2;r=w/2-2; col='#2f8f3a' if typ=='startEvent' else '#d52222'; sw=2 if typ=='startEvent' else 4
            s.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#fff" stroke="{col}" stroke-width="{sw}"/>')
            if n.get('name'): s.append(text(cx,y+h+20,txt_wrap(n['name'],24),10,600,fill=col))
    s.append('</svg>'); return ''.join(s)

def build_brief(model):
    b=model.get('brief',{})
    name=model['process'].get('name','Бизнес-процесс')
    goal=b.get('goal') or model['process'].get('goal') or 'показывает последовательность выполнения бизнес-процесса'
    start=b.get('start') or next((n['name'] for n in model['nodes'] if n['type']=='startEvent'),'инициации процесса')
    end=b.get('end') or next((n['name'] for n in model['nodes'] if n['type']=='endEvent'),'получения результата')
    checkpoints=b.get('checkpoints',[])
    loops=b.get('loops',[])
    lines=[f'# Краткое описание — {name}',f'Схема {goal}. Процесс начинается с «{start}» и последовательно проходит через действия ответственных участников.']
    if checkpoints: lines.append('Ключевые контрольные точки: '+', '.join(checkpoints)+'.')
    if loops: lines.append('При отклонениях предусмотрены циклы доработки: '+', '.join(loops)+'.')
    lines.append(f'Процесс завершается результатом «{end}».')
    return '\n\n'.join(lines)+'\n'

def validate(model,pool_bounds,waypoints,eps_status):
    nodes={n['id']:n for n in model['nodes']}; errors=[]; diag=0; endpoint=0; perp=0; cross_pool_seq=0; internal_msg=0; lane_cross=0
    pool_lanes={p['id']:{l['id'] for l in p.get('lanes',[])} for p in model['pools']}
    # node-lane and lane boundary
    for n in nodes.values():
        if n['lane'] not in pool_lanes.get(n['pool'],set()): errors.append(f"{n['id']}: invalid lane")
        p=next(p for p in model['pools'] if p['id']==n['pool']); li=[l['id'] for l in p['lanes']].index(n['lane']); py=pool_bounds[n['pool']][1]; lh=model['style']['lane_height']; top=py+li*lh; bottom=top+lh
        if n['y']<top or n['y']+n['height']>bottom: lane_cross+=1
    def on_border(pt,n,tol=.01):
        x,y=pt; bx,by,w,h=n['x'],n['y'],n['width'],n['height']
        return (((abs(x-bx)<tol or abs(x-(bx+w))<tol) and by-tol<=y<=by+h+tol) or ((abs(y-by)<tol or abs(y-(by+h))<tol) and bx-tol<=x<=bx+w+tol))
    for f in model['flows']:
        if f['source'] not in nodes or f['target'] not in nodes: errors.append(f"{f['id']}: broken ref"); continue
        s,t=nodes[f['source']],nodes[f['target']]
        if f['type']=='sequence' and s['pool']!=t['pool']: cross_pool_seq+=1
        if f['type']=='message' and s['pool']==t['pool']: internal_msg+=1
        pts=waypoints[f['id']]
        if f['type']=='sequence':
            if not on_border(pts[0],s) or not on_border(pts[-1],t): endpoint+=1
            for a,b in zip(pts,pts[1:]):
                if abs(a[0]-b[0])>.01 and abs(a[1]-b[1])>.01: diag+=1
            if len(pts)>=2:
                a,b=pts[-2],pts[-1]; dx=b[0]-a[0];dy=b[1]-a[1]; bx,by,w,h=t['x'],t['y'],t['width'],t['height']; horiz=abs(dy)<.01; vert=abs(dx)<.01
                side_lr=abs(b[0]-bx)<.01 or abs(b[0]-(bx+w))<.01; side_tb=abs(b[1]-by)<.01 or abs(b[1]-(by+h))<.01
                if not ((side_lr and horiz) or (side_tb and vert)): perp+=1
    # Detect Sequence Flow segments passing through unrelated BPMN nodes.
    def seg_hits_rect(a,b,n):
        x1,y1=a; x2,y2=b; rx,ry,rw,rh=n["x"],n["y"],n["width"],n["height"]; e=.01
        l,t,rr,bb=rx+e,ry+e,rx+rw-e,ry+rh-e
        if abs(y1-y2)<.01 and t<y1<bb:
            lo,hi=sorted([x1,x2]); return max(lo,l)<min(hi,rr)
        if abs(x1-x2)<.01 and l<x1<rr:
            lo,hi=sorted([y1,y2]); return max(lo,t)<min(hi,bb)
        return False
    through=0
    seq_flows=[f for f in model["flows"] if f["type"]=="sequence" and f["id"] in waypoints]
    for f in seq_flows:
        pts=waypoints[f["id"]]
        for a,b in zip(pts,pts[1:]):
            for nid,n in nodes.items():
                if nid in (f["source"],f["target"]): continue
                if seg_hits_rect(a,b,n): through+=1
    # Detect collinear overlapping segments from different Sequence Flows.
    def overlap(a,b,c,d):
        if abs(a[1]-b[1])<.01 and abs(c[1]-d[1])<.01 and abs(a[1]-c[1])<.01:
            p=sorted([a[0],b[0]]); q=sorted([c[0],d[0]])
            return min(p[1],q[1])-max(p[0],q[0])>.5
        if abs(a[0]-b[0])<.01 and abs(c[0]-d[0])<.01 and abs(a[0]-c[0])<.01:
            p=sorted([a[1],b[1]]); q=sorted([c[1],d[1]])
            return min(p[1],q[1])-max(p[0],q[0])>.5
        return False
    overlaps=0
    for i in range(len(seq_flows)):
        for j in range(i+1,len(seq_flows)):
            p1=waypoints[seq_flows[i]["id"]]; p2=waypoints[seq_flows[j]["id"]]; found=False
            for a,b in zip(p1,p1[1:]):
                for c,d in zip(p2,p2[1:]):
                    if overlap(a,b,c,d): overlaps+=1; found=True; break
                if found: break
    passed=not errors and diag==endpoint==perp==cross_pool_seq==internal_msg==lane_cross==through==overlaps==0
    report=f"""STATUS: {'PASS' if passed else 'FAIL'}\n\nStructural / geometry checks\n- broken/reference errors: {len(errors)}\n- diagonal Sequence Flow segments: {diag}\n- off-boundary endpoints: {endpoint}\n- non-perpendicular target entries: {perp}\n- Sequence Flow across Pools: {cross_pool_seq}\n- Message Flow inside same Pool: {internal_msg}\n- Tasks crossing Lane boundaries: {lane_cross}\n- flows through unrelated BPMN nodes: {through}\n- overlapping collinear Sequence Flow segments: {overlaps}\n- EPS: {eps_status}\n\nNotes\n- This is an internal structural/geometry validation.\n- Official OMG BPMN XSD validation is not claimed unless separately executed against official XSD files.\n"""
    return report,passed

def main():
    ap=argparse.ArgumentParser(description='Build BPMN 2.0 deliverable pack from Hermes process-model.json')
    ap.add_argument('model'); ap.add_argument('--out',default='./bpmn-output')
    args=ap.parse_args()
    try:
        model=load_model(args.model); passed=build(model,args.out)
        print('STATUS:', 'PASS' if passed else 'FAIL')
        print(Path(args.out).resolve())
        sys.exit(0 if passed else 1)
    except Exception as e:
        print('ERROR:',e,file=sys.stderr); sys.exit(2)
if __name__=='__main__': main()
