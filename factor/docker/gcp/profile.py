"""Strict inert Cloud Run v2 Job profile; performs no Google Cloud calls."""
import copy, hashlib, json, re
from pathlib import Path

PACKAGE=Path(__file__).resolve().parent; PROFILE_PATH=PACKAGE/"runtime-profile.json"; MAX_BYTES=512*1024
ID=re.compile(r"[a-z][a-z0-9-]{2,62}\Z"); SA=re.compile(r"[a-z][a-z0-9-]{2,62}@[a-z][a-z0-9-]{4,28}\.iam\.gserviceaccount\.com\Z"); IMAGE=re.compile(r"[a-z0-9-]+-docker\.pkg\.dev/[a-z][a-z0-9-]{4,28}/[a-z0-9._-]+/[a-z0-9._-]+@sha256:[a-f0-9]{64}\Z")
ROLES=("controller","executor","evaluator","checker","publisher"); OWNER={"controller":"execution","executor":"execution","evaluator":"custody","checker":"custody","publisher":"custody"}
COMMANDS={"controller":["factor-controller","run"],"executor":["factor-executor","run"],"evaluator":["factor-evaluator","aggregate"],"checker":["factor-checker","recompute"],"publisher":["factor-publisher","append"]}
OUTPUTS={"controller":"factor-controller-receipt-v1","executor":"factor-executor-structural-v1","evaluator":"factor-evaluator-aggregate-v1","checker":"factor-checker-aggregate-v1","publisher":"factor-publication-catalog-v1"}; REDACTION="factor-no-sensitive-output-v1"
INTENT={"controller":["provider-proxy.invoke","handoff.write"],"executor":["storage.objects.get-version","storage.objects.create-handoff","cloudkms.cryptoKeyVersions.useToDecrypt-dataset"],"evaluator":["storage.objects.get-checkpoint-version","storage.objects.get-label-version","aggregate.write"],"checker":["storage.objects.get-checkpoint-version","storage.objects.get-label-version","aggregate.verify"],"publisher":["aggregate.read","catalog.append","workflow.callback"]}
BLOCKERS=["billing-account-unresolved","control-project-unresolved","execution-project-unresolved","custody-project-unresolved","region-unresolved","dual-region-unresolved","artifact-registry-unresolved","image-digests-unresolved","service-accounts-unresolved","vpc-subnets-tags-unresolved","direct-vpc-receipt-unavailable","firewall-receipt-unavailable","vpc-sc-unverified","storage-buckets-unresolved","kms-keys-unresolved","label-object-policy-unresolved","workflow-unresolved","binary-authorization-unverified","cloud-run-conformance-unrun"]

class GcpProfileError(ValueError): pass
def require(x,c):
    if not x: raise GcpProfileError(c)
def canonical(v):
    try:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()
    except Exception:raise GcpProfileError("GCP_PROFILE_JSON_INVALID") from None
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
def _strict(v,k,c):require(type(v)is dict and set(v)==set(k),c);return v

def _job(v,r,syn):
    k={"name","project_role","region","image_digest","service_account","vpc","subnet","network_tag","containers","sidecars","execution_environment","ingress","vpc_egress","command","secrets","permissions","active_access","output_schema_id","redaction_policy_id","structured_stdout_only","raw_joined_rows_output","sensitive_logging","aggregate_only"};_strict(v,k,"GCP_JOB_SCHEMA")
    require(v["name"]==r and v["project_role"]==OWNER[r] and v["containers"]==1 and v["sidecars"]is False and v["execution_environment"]=="gen2" and v["ingress"]=="none" and v["vpc_egress"]=="all-traffic" and v["command"]==COMMANDS[r] and v["secrets"]==(["provider-proxy-reference"] if r=="controller" else[]) and v["permissions"]==INTENT[r] and v["active_access"]is False and v["output_schema_id"]==OUTPUTS[r] and v["redaction_policy_id"]==REDACTION and v["structured_stdout_only"]is True and v["raw_joined_rows_output"]is False and v["sensitive_logging"]is False and v["aggregate_only"]is(r in{"evaluator","checker"}),"GCP_JOB_SECURITY")
    if syn:require(type(v["region"])is str and ID.fullmatch(v["region"]) and type(v["image_digest"])is str and IMAGE.fullmatch(v["image_digest"]) and type(v["service_account"])is str and SA.fullmatch(v["service_account"]) and all(type(v[x])is str and ID.fullmatch(v[x])for x in("vpc","subnet","network_tag")),"GCP_JOB_IDENTITY")
    else:require(all(v[x]is None for x in("region","image_digest","service_account","vpc","subnet","network_tag")),"GCP_JOB_MUST_BLOCK")

def validate_profile(v):
    _strict(v,{"schema_version","kind","profile_id","status","trust_class","runnable","billing_account","projects","region","dual_region","platform","activation","resources","network","jobs","blockers","limitations"},"GCP_PROFILE_SCHEMA")
    require(type(v["schema_version"])is int and v["schema_version"]==1 and v["kind"]=="factor_gcp_cloud_run_profile" and v["profile_id"]=="factor-gcp-cloud-run-v1" and v["status"]in{"selected-disabled","synthetic-fixture"} and v["runnable"]is False and v["platform"]=={"service":"cloud-run-jobs","execution_environment":"gen2","scale_to_zero":True,"one_concern_per_job":True},"GCP_PROFILE_VERSION")
    syn=v["trust_class"]=="synthetic_fixture";require((syn and v["status"]=="synthetic-fixture")or(v["trust_class"]=="candidate_real"and v["status"]=="selected-disabled"),"GCP_PROFILE_TRUST")
    projects=_strict(v["projects"],{"control","execution","custody"},"GCP_PROJECTS")
    if syn:require(type(v["billing_account"])is str and ID.fullmatch(v["billing_account"]) and all(type(x)is str and ID.fullmatch(x)for x in projects.values())and len(set(projects.values()))==3 and type(v["region"])is str and ID.fullmatch(v["region"])and type(v["dual_region"])is str and ID.fullmatch(v["dual_region"]),"GCP_PROJECTS")
    else:require(v["billing_account"]is None and v["region"]is None and v["dual_region"]is None and all(x is None for x in projects.values()),"GCP_PROFILE_MUST_BLOCK")
    activation=_strict(v["activation"],{"runtime_invocation","protected_labels","publication","production_retention_lock","api_enablement","account_receipt_sha256","network_receipt_sha256","image_receipt_sha256","label_policy_receipt_sha256","publication_policy_receipt_sha256"},"GCP_ACTIVATION_SCHEMA");require(activation=={"runtime_invocation":False,"protected_labels":False,"publication":False,"production_retention_lock":False,"api_enablement":False,"account_receipt_sha256":None,"network_receipt_sha256":None,"image_receipt_sha256":None,"label_policy_receipt_sha256":None,"publication_policy_receipt_sha256":None},"GCP_ACTIVATION_FORBIDDEN")
    resources=_strict(v["resources"],{"artifact_registry","checkpoint_bucket","label_bucket","release_bucket","kms_checkpoint_key","kms_evaluation_key","kms_publication_key","kms_revocation_key","workflow","vpc_sc_perimeter"},"GCP_RESOURCES");require((syn and all(type(x)is str and ID.fullmatch(x)for x in resources.values()))or(not syn and all(x is None for x in resources.values())),"GCP_RESOURCES")
    require(v["network"]=={"executor":{"direct_vpc":True,"all_traffic":True,"default_deny":True,"public_egress":False,"allowed_destinations":["restricted-googleapis-storage-kms"],"restricted_vip_cidrs":["199.36.153.4/30"],"private_dns":["restricted.googleapis.com","storage.googleapis.com","cloudkms.googleapis.com"],"vpc_sc_candidate":True},"controller":{"direct_vpc":True,"provider_proxy_only":True,"public_ingress":False},"custody":{"direct_vpc":True,"private_storage_only":True,"public_ingress":False}},"GCP_NETWORK")
    jobs=_strict(v["jobs"],set(ROLES),"GCP_JOB_ROSTER");[_job(jobs[r],r,syn)for r in ROLES]
    if syn:
        for f in("service_account","vpc","subnet","network_tag"):vals=[jobs[r][f]for r in ROLES];require(len(vals)==len(set(vals)),"GCP_CONCERN_REUSE")
    require(v["blockers"]==([]if syn else BLOCKERS)and v["limitations"]==(["fixture-only","no-real-cloud","no-values","no-outcomes"]if syn else["selected-disabled","no-cloud-resources","no-real-data","no-runtime"]),"GCP_BLOCKERS");return v

def load_profile(path=PROFILE_PATH):
    try:raw=Path(path).read_bytes();require(0<len(raw)<=MAX_BYTES,"GCP_PROFILE_SIZE");return validate_profile(json.loads(raw))
    except GcpProfileError:raise
    except Exception:raise GcpProfileError("GCP_PROFILE_UNAVAILABLE")from None

def _job_resource(p,r):
    j=p["jobs"][r];project=p["projects"][j["project_role"]];name=f"projects/{project}/locations/{j['region']}/jobs/factor-{r}"
    task={"containers":[{"image":j["image_digest"],"command":[j["command"][0]],"args":j["command"][1:],"resources":{"limits":{"cpu":"1","memory":"512Mi"}},"env":[]}],"serviceAccount":j["service_account"],"timeout":"600s","maxRetries":0,"vpcAccess":{"networkInterfaces":[{"network":f"projects/{project}/global/networks/{j['vpc']}","subnetwork":f"projects/{project}/regions/{j['region']}/subnetworks/{j['subnet']}","tags":[j["network_tag"]]}],"egress":"ALL_TRAFFIC"}}
    return {"job":{"name":name,"labels":{"factor-role":r},"template":{"taskCount":1,"parallelism":1,"template":task},"launchStage":"GA","binaryAuthorization":{"useDefault":True}},"contract":{"outputSchema":j["output_schema_id"],"redactionPolicy":j["redaction_policy_id"],"structuredStdoutOnly":True,"rawRows":False,"active":False}}

def render_templates(profile):
    p=validate_profile(copy.deepcopy(profile));require(p["trust_class"]=="synthetic_fixture","GCP_TEMPLATE_FIXTURE_ONLY")
    jobs={r:_job_resource(p,r)for r in ROLES};iam={};
    for r in ROLES:
        j=p["jobs"][r];job=jobs[r]["job"]["name"];invoker=p["jobs"]["controller"]["service_account"]if r=="executor"else j["service_account"]
        iam[r]={"job":job,"serviceAccount":j["service_account"],"invoker":invoker,"allow":{"permission":"run.jobs.run","resource":job},"denyPermissions":["run.jobs.runWithOverrides","run.jobs.update","iam.serviceAccounts.actAs"],"workloadPermissions":j["permissions"],"active":False}
    net=p["network"]["executor"];firewall={"executor":{"targetTag":p["jobs"]["executor"]["network_tag"],"routes":[{"destinationRange":"199.36.153.4/30","nextHop":"default-internet-gateway","privateGoogleAccess":True}],"dns":net["private_dns"],"rules":[{"priority":900,"action":"allow","direction":"EGRESS","destinationRanges":["199.36.153.4/30"],"protocol":"tcp","ports":[443]},{"priority":65534,"action":"deny","direction":"EGRESS","destinationRanges":["0.0.0.0/0"],"protocol":"all","ports":[]}],"vpcServiceControls":{"candidate":True,"services":["storage.googleapis.com","cloudkms.googleapis.com"]},"publicEgress":False}}
    return {"schema_version":1,"kind":"gcp_cloud_run_inert_templates","profile_sha256":digest(p),"jobs":jobs,"iam_policy_specs":iam,"network_policy_spec":firewall,"activation":p["activation"]}

def validate_templates(v,profile):
    require(v==render_templates(profile),"GCP_TEMPLATE_MISMATCH");return v
