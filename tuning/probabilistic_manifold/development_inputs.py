"""Concrete source-bound development features/support and lazy labels for protocol v2."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence
from .core import _read_stable_source, open_root_anchor
from .rolling_origin import RollingError
from .rolling_outcomes import exact_targets, qqq_daily_3x_drawdown


def _read_bound(root:Path,relative:str,sha256:str,byte_count:int)->bytes:
    with open_root_anchor(root,"development source root") as anchor: payload=_read_stable_source(anchor,relative)
    if len(payload)!=byte_count or hashlib.sha256(payload).hexdigest()!=sha256: raise RollingError("CONFIG_INVALID","raw source hash/bytes mismatch")
    return payload


def _series(payload:bytes,symbol:str)->tuple[list[dt.date],list[float]]:
    try:
        result=json.loads(payload)["chart"]["result"][0]; timestamps=result["timestamp"]; prices=result["indicators"]["adjclose"][0]["adjclose"]
    except Exception as exc: raise RollingError("CONFIG_INVALID","source schema") from exc
    if result["meta"]["symbol"]!=symbol or len(timestamps)!=len(prices): raise RollingError("CONFIG_INVALID","source symbol/length")
    dates=[dt.datetime.fromtimestamp(int(value),dt.timezone.utc).date() for value in timestamps]
    values=[]
    for value in prices:
        if type(value) not in (int,float) or not math.isfinite(float(value)) or float(value)<=0: raise RollingError("NUMERIC_FAILURE","source adjusted price")
        values.append(float(value))
    if dates!=sorted(dates) or len(set(dates))!=len(dates): raise RollingError("DATA_CHRONOLOGY","source dates")
    return dates,values


def _features(tqqq:Sequence[float],qqq:Sequence[float],index:int)->dict[str,float]:
    logs=[math.log(tqqq[j]/tqqq[j-1]) for j in range(index-20,index+1)]; center=sum(logs)/len(logs); downside=[math.log(tqqq[j]/tqqq[j-1]) for j in range(index-62,index+1)]
    return {"tqqq_return_21":tqqq[index]/tqqq[index-21]-1,"tqqq_return_63":tqqq[index]/tqqq[index-63]-1,"tqqq_return_126":tqqq[index]/tqqq[index-126]-1,"distance_from_126_high":tqqq[index]/max(tqqq[index-125:index+1])-1,"realized_volatility_21":math.sqrt(252*sum((value-center)**2 for value in logs)/len(logs)),"downside_semivariance_63":252*sum(min(value,0)**2 for value in downside)/len(downside),"qqq_return_126":qqq[index]/qqq[index-126]-1}


def _quantile(values:Sequence[float],q:float)->float:
    ordered=sorted(float(value) for value in values); position=(len(ordered)-1)*q; low,high=math.floor(position),math.ceil(position)
    return ordered[low] if low==high else ordered[low]+(ordered[high]-ordered[low])*(position-low)


def _support(records:list[dict[str,Any]],position:int,k:int=12,minimum_training_rows:int=18,inside_quantile:float=.95,edge_quantile:float=.99)->dict[str,Any]:
    row=records[position]; training=[item for item in records[:position] if item["maturity_index"]<=row["origin_index"]-126-21]
    if len(training)<max(minimum_training_rows,k+1): return {"status":"inconclusive","training_count":len(training),"query_k_distance":None,"training_loo_q95":None,"training_loo_q99":None,"reason":"minimum_training_origins_not_met"}
    names=sorted(row["features"]); centers={}; scales={}
    for name in names:
        values=[item["features"][name] for item in training]; center=median(values); mad=median(abs(value-center) for value in values); scale=1.4826*mad
        if not math.isfinite(scale) or scale<=1e-12: return {"status":"inconclusive","training_count":len(training),"query_k_distance":None,"training_loo_q95":None,"training_loo_q99":None,"reason":"zero_mad"}
        centers[name]=center; scales[name]=scale
    def vector(features:Mapping[str,float])->list[float]: return [(features[name]-centers[name])/scales[name] for name in names]
    train_vectors=[vector(item["features"]) for item in training]; query=vector(row["features"])
    def distance(left:Sequence[float],right:Sequence[float])->float: return math.sqrt(sum((a-b)**2 for a,b in zip(left,right)))
    query_distances=sorted(distance(query,item) for item in train_vectors); query_k=query_distances[k-1]
    loo=[]
    for index,item in enumerate(train_vectors):
        distances=sorted(distance(item,other) for j,other in enumerate(train_vectors) if j!=index); loo.append(distances[k-1])
    q95=_quantile(loo,inside_quantile); q99=_quantile(loo,edge_quantile)
    status="inside" if query_k<=q95 else "edge" if query_k<=q99 else "outside"
    return {"status":status,"training_count":len(training),"query_k_distance":query_k,"training_loo_q95":q95,"training_loo_q99":q99,"reason":None}


def compute_development_inputs(config:Mapping[str,Any],development_split:Mapping[str,Any],source_root:Path,session_roster:Mapping[str,Any],authority_base:Mapping[str,str])->tuple[dict[str,Any],dict[str,Any]]:
    spec=config["input_sources"]; td,tv=_series(_read_bound(source_root,spec["tqqq_path"],spec["tqqq_sha256"],spec["tqqq_bytes"]),"TQQQ"); qd,qv_raw=_series(_read_bound(source_root,spec["qqq_path"],spec["qqq_sha256"],spec["qqq_bytes"]),"QQQ")
    roster=[dt.date.fromisoformat(value) for value in session_roster["sessions"]]
    if td!=roster: raise RollingError("CONFIG_INVALID","TQQQ roster mismatch")
    qmap=dict(zip(qd,qv_raw))
    if any(date not in qmap for date in roster): raise RollingError("CONFIG_INVALID","QQQ roster mismatch")
    qv=[qmap[date] for date in roster]; rows=[]
    for origin in development_split["groups"]["primary"]:
        index=origin["origin_index"]; rows.append({"origin_id":origin["origin_id"],"origin_index":index,"origin_date":origin["origin_date"],"maturity_index":origin["maturity_index"],"maturity_date":origin["maturity_date"],"features":_features(tv,qv,index)})
    geometry=config["support_geometry"]; support=[{"origin_id":row["origin_id"],**_support(rows,i,geometry["k"],geometry["minimum_training_rows"],geometry["inside_quantile"],geometry["edge_quantile"])} for i,row in enumerate(rows)]
    common={**authority_base,"builder_code_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"tqqq_raw_sha256":spec["tqqq_sha256"],"qqq_raw_sha256":spec["qqq_sha256"]}
    feature_artifact={"schema_version":"development-features-v2","authority":common,"records":[{"origin_id":row["origin_id"],"origin_index":row["origin_index"],"origin_date":row["origin_date"],"features":row["features"]} for row in rows],"contains_labels":False,"contains_outcomes":False,"protected_outcomes_accessed":False}
    support_artifact={"schema_version":"development-support-v2","authority":common,"records":support,"method":"training_only_median_mad_loo_kth_neighbor_v2","contains_labels":False,"contains_outcomes":False,"protected_outcomes_accessed":False}
    return feature_artifact,support_artifact


class ConcreteDevelopmentLabelLoader:
    """Reads bound raw files only when load() is explicitly called for allowlisted IDs."""
    def __init__(self,config:Mapping[str,Any],source_root:Path,primary_rows:Sequence[Mapping[str,Any]]):
        self.config=dict(config); self.source_root=source_root; self.rows={row["origin_id"]:dict(row) for row in primary_rows}
    def load(self,ids:Sequence[str])->Mapping[str,Mapping[str,Any]]:
        if not ids or any(item not in self.rows for item in ids): raise RollingError("PROTECTED_ACCESS_DENIED","label ID outside development split")
        spec=self.config["input_sources"]; td,tv=_series(_read_bound(self.source_root,spec["tqqq_path"],spec["tqqq_sha256"],spec["tqqq_bytes"]),"TQQQ"); qd,qv_raw=_series(_read_bound(self.source_root,spec["qqq_path"],spec["qqq_sha256"],spec["qqq_bytes"]),"QQQ"); qmap=dict(zip(qd,qv_raw)); qv=[qmap[date] for date in td]
        result={}
        for item in ids:
            row=self.rows[item]; values=exact_targets(tv,qv,row["origin_index"],126); qpath=qv[row["origin_index"]:row["origin_index"]+127]
            result[item]={"return":values["return"],"max_drawdown":values["max_drawdown"],"relative_qqq":values["relative_qqq"],"material_loss":values["material_loss"],"qqq_3x_path_drawdown":qqq_daily_3x_drawdown(qpath)}
        return result
