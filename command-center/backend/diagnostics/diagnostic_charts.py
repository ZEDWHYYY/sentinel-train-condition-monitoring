"""Small evidence-linked chart set, derived from the same uploaded samples."""
from __future__ import annotations
import numpy as np
from . import acv,door,rail,shm
from .common import chart,minmax_downsample


def build(sub,data,res,model,source):
    advice=res["diagnosis"]
    if sub=="door":
        item=next(i for i in res["items"] if i["id"]==advice["selected_item"])
        cs=door.cycle_chart(data,item,model,source)
        cs[0]["id"],cs[1]["id"]="door-current","door-position"
        cs[0]["caption"]+=f" This movement's integral is {item['features']['current_integral_mAs']:.1f} mA·s; decision cutoff {item['decision']['cutoff']:.1f} mA·s. An integral threshold is not an instantaneous-current threshold."
        series=[{"name":"Current integral","role":"primary","x":[i["index"]+1 for i in res["items"]],"y":[i["features"]["current_integral_mAs"] for i in res["items"]]},
                {"name":"Decision cutoff","role":"reference","x":[i["index"]+1 for i in res["items"]],"y":[i["decision"]["cutoff"] for i in res["items"]]}]
        overview=chart("Current integral against its cutoff","Movement current integral","mA·s","Movement number",source,series,
                       bands=[{"x0":i["index"]+.75,"x1":i["index"]+1.25,"tone":"fault","label":"Above cutoff"} for i in res["items"] if i["prediction"]!="Normal"],
                       caption="Shaded movements exceed the direction-specific cutoff. Hover to compare the measured integral and cutoff.")
        overview["id"]="door-integrals"
        return [overview,*cs]
    if sub=="acv":
        car=advice.get("selected_car",data.cars[0])
        ev=acv.car_evidence(data,model["params"])
        x=((data.time-data.time.iloc[0]).dt.total_seconds()/3600).to_numpy()
        y=ev["peer_residual"][car].to_numpy(float)
        series=[{"name":f"Car {car} above cooling peers","role":"primary",**minmax_downsample(x,y)},
                {"name":"Inspection reference +1 K","role":"reference","x":[float(x[0]),float(x[-1])],"y":[1,1]}]
        bands=[]
        active=np.isfinite(y)&(y>1)
        edges=np.flatnonzero(np.diff(np.r_[0,active.astype(int),0]))
        for a,b in zip(edges[::2],edges[1::2]):
            bands.append({"x0":float(x[a]),"x1":float(x[min(b,len(x)-1)]),"tone":"fault","label":"Above peers by 1 K"})
        c=chart(f"Car {car}: temperature above cooling peers","Cabin minus median of other settled cooling cars","K",f"Hours since {data.time.iloc[0]}",source,series,bands=bands,
                caption="Only valid, settled cooling comparisons are plotted. Gaps are excluded observations. The 1 K inspection reference is an advisory policy, not a calibrated leak threshold.")
        c["id"]="acv-temperature"
        ranked=acv.score_chart(res["items"][0]);ranked["id"]="acv-ranking"
        ranked["caption"]="Mean temperature above contemporaneous settled cooling peers, K. This is an uncalibrated ranking, not a leak probability."
        return [c,ranked]
    if sub=="rail":
        item=res["items"][0]
        car=int(advice["selected_car"]);pos=advice["selected_position"]
        sides=rail.sides_chart(item,source);sides["id"]="rail-sides"
        waveform=rail.waveform_chart(data,car,pos,"vibration",source);waveform["id"]="rail-waveform"
        if advice["condition"]!="Normal":
            waveform["bands"]=[{"x0":0,"x1":len(data.data)/rail.FS,"tone":"fault","label":"Recording requiring review"}]
            waveform["caption"]+=" Shading identifies the assessed recording, not a localized defect: the decision uses whole-recording features."
        spectrum=rail.psd_chart(data,car,pos,"vibration",model,source);spectrum["id"]="rail-spectrum"
        spectrum["caption"]+=f" Frozen detection score {item['decision']['stage1_fault_score']:.3f} (threshold 0.5); spectrum is supporting evidence, not the entire feature vector."
        return [sides,waveform,spectrum]
    it=res["items"][0]
    trace=shm.trace_chart(data,source);trace["id"]="shm-trace"
    a=int(np.argmax(data.x));b=int(np.argmin(data.x))
    idx=data.sample_index if data.sample_index is not None else np.arange(len(data.x))
    neighborhood=max(20,int(.005*len(idx)))
    trace["bands"]=[{"x0":int(idx[max(0,k-neighborhood)]),"x1":int(idx[min(len(idx)-1,k+neighborhood)]),"tone":"context","label":"Stress extremum"} for k in (a,b)]
    trace["caption"]+=" Shading marks a 1%-of-recording neighborhood around each stress extremum, not a failure threshold; stress units are undocumented."
    ranges,_,_=shm.cycles(data.x,model["gate"])
    hist=shm.cycle_hist_chart(it,ranges,model,source);hist["id"]="shm-cycles"
    return [trace,hist]
