import copy
import hashlib
import hmac
import json
from pathlib import Path
import threading
import unittest

from tuning.factor_mining.trusted_authority.aws import contract

SHA_A, SHA_B, SHA_C, SHA_D = (c * 64 for c in "abcd")
T0, T1, T2, T3 = (f"2026-11-05T0{hour}:00:00Z" for hour in range(4))
T_RETAIN = "2026-11-07T00:00:00Z"


class FixtureVerifier:
    """Fixture-only signing port; never a production KMS substitute."""
    def __init__(self):
        self.secrets = {purpose: (purpose.encode() * 32)[:32] for purpose in contract.PURPOSES}
    def key_version(self, purpose): return f"{purpose}-key-v1"
    def public_hash(self, purpose): return hashlib.sha256((purpose + "-public").encode()).hexdigest()
    def sign(self, value, purpose):
        result = copy.deepcopy(value)
        result.update(signer_key_version=self.key_version(purpose),
                      signer_public_key_sha256=self.public_hash(purpose),
                      signature_encoding="FIXTURE_HMAC_SHA256_HEX", signature="pending")
        unsigned = {k: result[k] for k in result if k != "signature"}
        result["signature"] = hmac.new(self.secrets[purpose], contract.canonical(unsigned),
                                       hashlib.sha256).hexdigest()
        return result
    def verify(self, unsigned_bytes, signature, *, encoding, key_version,
               public_key_sha256, purpose):
        if encoding != "FIXTURE_HMAC_SHA256_HEX" or key_version != self.key_version(purpose): return False
        if public_key_sha256 != self.public_hash(purpose): return False
        expected = hmac.new(self.secrets[purpose], unsigned_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


def key_status(verifier, purpose="checkpoint", key_id=None, status="active",
               previous=None, when=T0):
    kid = key_id or f"{purpose}-key-v1"; disabled = status != "active"
    value = {"schema_version":1,"kind":"aws_kms_key_status","key_id":kid,
      "purpose":purpose,"primary_key_arn":f"arn:aws:kms:us-east-1:222222222222:key/mrk-{kid}",
      "replica_key_arn":f"arn:aws:kms:us-west-2:222222222222:key/mrk-{kid}",
      "alias":f"alias:{purpose}","public_key_sha256":verifier.public_hash(purpose),
      "status":status,"effective_at":when,"previous_status_sha256":previous,
      "primary_enabled":not disabled,"replica_enabled":not disabled,
      "grants_revoked":disabled,"policy_sha256":SHA_B}
    return verifier.sign(value,"revocation")


def locked(bucket,key,version,content=SHA_A,verified=T0,retain=T_RETAIN,days=1):
    return {"bucket_arn":f"arn:aws:s3:::{bucket}","key":key,"version_id":version,
      "content_sha256":content,"verified_at":verified,"retain_until":retain,
      "minimum_retention_days":days,"object_lock_mode":"COMPLIANCE","delete_marker":False}


def receipt(verifier,sequence,epoch,manifest,checkpoint_object):
    value={"schema_version":1,"kind":"aws_checkpoint_commit_receipt","epoch":epoch,
      "sequence":sequence,"manifest_sha256":manifest,
      "checkpoint_object_sha256":contract.digest(checkpoint_object),"issued_at":T1}
    return verifier.sign(value,"checkpoint")


def commit(verifier,sequence=1,previous=None,epoch=1,region="us-east-1",transition=None,idem=None):
    manifest=SHA_A if sequence==1 else SHA_B
    checkpoint=locked("checkpoint-bucket",f"checkpoints/{sequence:020d}.json",
                      f"checkpoint-version-{sequence}",manifest)
    signed_receipt=receipt(verifier,sequence,epoch,manifest,checkpoint)
    status=key_status(verifier)
    value={"schema_version":1,"kind":"aws_checkpoint_commit","epoch":epoch,"sequence":sequence,
      "previous_manifest_sha256":previous,"manifest_sha256":manifest,
      "idempotency_key":idem or f"run-{sequence}","checkpoint_object":checkpoint,
      "commit_receipt":signed_receipt,
      "commit_receipt_object":locked("receipt-bucket",f"commit-receipts/{sequence:020d}.json",
          f"receipt-version-{sequence}",contract.digest(signed_receipt)),
      "writer_region":region,"key_status_sha256":contract.digest(status),
      "recovery_transition_sha256":transition,"create_only":True,"single_writer":True}
    return verifier.sign(value,"checkpoint")


class AwsAuthorityProfileTests(unittest.TestCase):
    def setUp(self): self.verifier=FixtureVerifier()

    def test_tracked_profile_is_exact_selected_disabled(self):
        value=contract.load_profile(); self.assertEqual(value,contract.expected_profile())
        self.assertEqual(value["status"],"selected-disabled"); self.assertFalse(value["activation_allowed"])
        self.assertEqual(value["blockers"],contract.BLOCKERS)
        self.assertTrue(all(v is None for v in value["accounts"].values()))

    def test_guessed_values_or_weakened_controls_fail(self):
        mutations=[]
        for path,value in ((('activation_allowed',),True),(('accounts','compute'),"111111111111"),
          (('checkpoint','retention_days'),365),(('checkpoint','idempotency_item_required'),False),
          (('kms_keys','checkpoint','account_scope'),"compute"),
          (('publication','two_distinct_approvers_required'),False)):
            changed=contract.expected_profile(); target=changed
            for part in path[:-1]: target=target[part]
            target[path[-1]]=value; mutations.append(changed)
        for value in mutations:
            with self.assertRaises(contract.AwsAuthorityError): contract.validate_profile(value)

    def test_locked_objects_retention_versions_and_signed_receipts(self):
        status=key_status(self.verifier); first=commit(self.verifier)
        self.assertEqual(contract.validate_checkpoint_commit(first,key_status=status,verifier=self.verifier),first)
        cases=[]
        expired=copy.deepcopy(first); expired["checkpoint_object"]["retain_until"]=T0; cases.append(expired)
        marker=copy.deepcopy(first); marker["checkpoint_object"]["delete_marker"]=True; cases.append(marker)
        latest=copy.deepcopy(first); latest["checkpoint_object"]["key"]="latest.json"; cases.append(latest)
        forged=copy.deepcopy(first); forged["commit_receipt"]["signature"]="0"*64; cases.append(forged)
        wrong_hash=copy.deepcopy(first); wrong_hash["commit_receipt_object"]["content_sha256"]=SHA_D; cases.append(wrong_hash)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(contract.AwsAuthorityError):
                contract.validate_checkpoint_commit(value,key_status=status,verifier=self.verifier)
        with self.assertRaises(TypeError): contract.validate_key_status(status)  # verifier is mandatory

    def test_multi_region_key_lifecycle_rotation_revocation_and_history(self):
        for purpose in contract.PURPOSES:
            status = key_status(self.verifier, purpose, f"{purpose}-key-v1")
            self.assertEqual(contract.validate_key_status(status, self.verifier), status)
            self.assertEqual(contract.historical_public_key(status, purpose, self.verifier),
                             self.verifier.public_hash(purpose))
        active=key_status(self.verifier); self.assertEqual(contract.historical_public_key(active,"checkpoint",self.verifier),self.verifier.public_hash("checkpoint"))
        retired=key_status(self.verifier,status="retired",when=T1)
        new=key_status(self.verifier,key_id="checkpoint-key-v2",previous=contract.digest(retired),when=T2)
        self.assertEqual(contract.validate_key_rotation(retired,new,self.verifier),new)
        wrong_account=copy.deepcopy(new); wrong_account["replica_key_arn"]=wrong_account["replica_key_arn"].replace("222222222222","333333333333")
        with self.assertRaisesRegex(contract.AwsAuthorityError,"KMS_REPLICA_INVALID"): contract.validate_key_status(wrong_account,self.verifier)
        wrong_mrk=copy.deepcopy(new); wrong_mrk["replica_key_arn"]=wrong_mrk["replica_key_arn"].replace("mrk-checkpoint-key-v2","mrk-other")
        with self.assertRaises(contract.AwsAuthorityError): contract.validate_key_status(wrong_mrk,self.verifier)
        revoked=key_status(self.verifier,status="revoked",when=T1)
        self.assertEqual(contract.historical_public_key(revoked,"checkpoint",self.verifier),self.verifier.public_hash("checkpoint"))

    def test_atomic_idempotency_unknown_outcome_and_concurrency(self):
        status=key_status(self.verifier); backend=contract.FixtureDynamoBackend(); candidate=commit(self.verifier)
        with self.assertRaises(contract.UnknownOutcome):
            backend.transact_commit(candidate,key_status=status,verifier=self.verifier,unknown_after_write=True)
        self.assertTrue(backend.reconcile(candidate["idempotency_key"],contract.digest(candidate)))
        replay,created=backend.transact_commit(copy.deepcopy(candidate),key_status=status,verifier=self.verifier)
        self.assertFalse(created); self.assertEqual(replay,candidate); self.assertEqual(backend.latest()["sequence"],1)
        other=contract.FixtureDynamoBackend(); results=[]; errors=[]
        def worker():
            try: results.append(other.transact_commit(copy.deepcopy(candidate),key_status=status,verifier=self.verifier)[1])
            except Exception as exc: errors.append(type(exc).__name__)
        threads=[threading.Thread(target=worker) for _ in range(8)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(errors,[]); self.assertEqual(results.count(True),1); self.assertEqual(results.count(False),7)

    def test_signed_current_authorization_requires_publication_key(self):
        checkpoint=commit(self.verifier); pub=key_status(self.verifier,"publication","publication-key-v1")
        unsigned={"schema_version":1,"kind":"aws_publication_authorization","authorization_id":"auth-1",
          "epoch":1,"sequence":1,"checkpoint_sha256":contract.digest(checkpoint),
          "purpose":"performance_publication","payload_sha256":SHA_B,
          "key_status_sha256":contract.digest(pub),"issued_at":T1,"expires_at":T3,"state":"active"}
        value=self.verifier.sign(unsigned,"publication")
        self.assertEqual(contract.validate_authorization(value,current_checkpoint=checkpoint,
          purpose="performance_publication",payload_sha256=SHA_B,key_status=pub,verifier=self.verifier,now=T2),value)
        with self.assertRaises(contract.AwsAuthorityError):
            contract.validate_authorization(value,current_checkpoint=checkpoint,purpose="performance_publication",
              payload_sha256=SHA_B,key_status=key_status(self.verifier),verifier=self.verifier,now=T2)
        forged=copy.deepcopy(value); forged["signature"]="0"*64
        with self.assertRaises(contract.AwsAuthorityError):
            contract.validate_authorization(forged,current_checkpoint=checkpoint,purpose="performance_publication",
              payload_sha256=SHA_B,key_status=pub,verifier=self.verifier,now=T2)
        with self.assertRaises(contract.AwsAuthorityError):
            contract.validate_authorization(value,current_checkpoint=checkpoint,purpose="performance_publication",
              payload_sha256=SHA_B,key_status=pub,verifier=self.verifier,now=T3)

    def test_signed_recovery_transition_is_internally_validated_by_commit(self):
        checkpoint_key=key_status(self.verifier); recovery_key=key_status(self.verifier,"revocation","revocation-key-v1")
        first=commit(self.verifier); current={"epoch":1,"sequence":1,"manifest_sha256":first["manifest_sha256"],"writer_region":"us-east-1"}
        unsigned={"schema_version":1,"kind":"aws_recovery_epoch_transition","from_region":"us-east-1",
          "to_region":"us-west-2","new_epoch":2,"prior_manifest_sha256":first["manifest_sha256"],
          "prior_checkpoint_sha256":contract.digest(current),"primary_fenced":True,"chain_verified":True,
          "merge_heads":False,"key_status_sha256":contract.digest(recovery_key),"issued_at":T2}
        transition=self.verifier.sign(unsigned,"revocation")
        second=commit(self.verifier,2,first["manifest_sha256"],2,"us-west-2",contract.digest(transition))
        self.assertEqual(contract.validate_checkpoint_commit(second,current,key_status=checkpoint_key,
          verifier=self.verifier,recovery_transition=transition,recovery_key_status=recovery_key),second)
        forged=copy.deepcopy(transition); forged["signature"]="0"*64
        with self.assertRaises(contract.AwsAuthorityError):
            contract.validate_checkpoint_commit(second,current,key_status=checkpoint_key,verifier=self.verifier,
              recovery_transition=forged,recovery_key_status=recovery_key)

    def test_schemas_exact_and_json_clean(self):
        root=Path(contract.PACKAGE); self.assertEqual(json.loads((root/"aws-authority-profile-v1.schema.json").read_text())["const"],contract.expected_profile())
        schemas={"checkpoint-commit-v1.schema.json":contract.COMMIT_KEYS,
          "commit-receipt-v1.schema.json":contract.RECEIPT_KEYS,
          "authorization-v1.schema.json":contract.AUTHORIZATION_KEYS,
          "recovery-transition-v1.schema.json":contract.RECOVERY_KEYS,
          "key-status-v1.schema.json":contract.KEY_STATUS_KEYS}
        for name,fields in schemas.items():
            value=json.loads((root/name).read_text()); self.assertEqual(set(value["required"]),set(value["properties"])); self.assertEqual(set(value["required"]),fields)
        for p in root.glob("*.json"): json.loads(p.read_text())
        tracked=" ".join(p.read_text().lower() for p in root.glob("*.json"))
        for marker in ("api_key","password","secret=","aws_access_key"): self.assertNotIn(marker,tracked)


if __name__=="__main__": unittest.main()
