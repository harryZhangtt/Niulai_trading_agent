"""Exact target formulas for rolling protocol v2; no I/O or execution entrypoint."""
from __future__ import annotations
import math
from typing import Sequence, Any
from .rolling_origin import RollingError

THRESHOLDS={126:-0.25,252:-0.40}

def _prices(values:Sequence[float],label:str)->list[float]:
    result=[]
    for value in values:
        if type(value) not in (int,float) or not math.isfinite(float(value)) or float(value)<=0: raise RollingError("NUMERIC_FAILURE",f"invalid {label} price")
        result.append(float(value))
    return result

def exact_targets(tqqq:Sequence[float],qqq:Sequence[float],origin_index:int,horizon:int)->dict[str,Any]:
    if horizon not in THRESHOLDS or type(origin_index) is not int or origin_index<0: raise RollingError("CONFIG_INVALID","unsupported horizon/origin")
    tp,qp=_prices(tqqq,"TQQQ"),_prices(qqq,"QQQ")
    end=origin_index+horizon
    if len(tp)!=len(qp) or end>=len(tp): raise RollingError("DATA_CHRONOLOGY","incomplete aligned horizon")
    path=tp[origin_index:end+1]; peak=path[0]; drawdown=0.0
    for price in path:
        peak=max(peak,price); drawdown=min(drawdown,price/peak-1)
    tr=tp[end]/tp[origin_index]-1; qr=qp[end]/qp[origin_index]-1
    return {"return":tr,"max_drawdown":drawdown,"relative_qqq":tr-qr,"material_loss":int(drawdown<=THRESHOLDS[horizon]),"threshold":THRESHOLDS[horizon],"horizon":horizon,"unit_continuous":"decimal_return","unit_binary":"zero_or_one"}

def qqq_daily_3x_drawdown(path:Sequence[float])->float:
    prices=_prices(path,"QQQ"); value=1.0; peak=1.0; drawdown=0.0
    for left,right in zip(prices,prices[1:]):
        multiplier=1+3*(right/left-1)
        if multiplier<=0: raise RollingError("NUMERIC_FAILURE","QQQ daily 3x proxy liquidation/floor reached")
        value*=multiplier; peak=max(peak,value); drawdown=min(drawdown,value/peak-1)
    return drawdown
