from .contracts import validate_cleanup
def receipt(process):
    complete=process is not None and process["reaps"]==1 and process["descriptors_closed"]==2
    x={"state":"complete" if complete else ("not_started" if process is None else "uncertain"),"process_group_reaped":False if process is None else process["reaps"]==1,"descriptors_closed":False if process is None else process["descriptors_closed"]==2,"residuals":[] if complete or process is None else ["synthetic_uncertainty"]};validate_cleanup(x);return x
