from __future__ import annotations
import hashlib
from pathlib import Path
import tempfile,unittest
from shared.research_sources.nasdaq_listed import (
    MAX_SOURCE_AGE_CALENDAR_DAYS,SOURCE_URL,NasdaqListedError,_RejectRedirects,
    acquire_nasdaq_listed,parse_nasdaq_listed,
)
HEADER=b"Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\r\n"
def fixture(*rows,trailer=b"File Creation Time: 1110202612:30|||||||\r\n"):return HEADER+b"".join(row+b"\r\n" for row in rows)+trailer
A=b"AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N";S=b"SPACE|  Acme   Holdings  |Q|N|N|100|N|N";B=b"BRK.B|Berkshire Hathaway Inc. Class B|G|N||100|N|N";W=b"AACGW|Warrant Security|S|N|D|100|N|N"
class Response:
 def __init__(self,raw,*,url=SOURCE_URL,headers=None,status=200):self.raw=raw;self.url=url;self.headers=headers if headers is not None else {"Content-Length":str(len(raw)),"Content-Type":"text/plain"};self.status=status;self.closed=False
 def getcode(self):return self.status
 def geturl(self):return self.url
 def read(self,limit):return self.raw[:limit]
 def close(self):self.closed=True
class NasdaqListedTests(unittest.TestCase):
 def test_parse_preserves_flags_and_deterministic_identity(self):
  raw=fixture(W,B,A);one=parse_nasdaq_listed(raw,retrieved_at="2026-11-10T18:00:00Z");two=parse_nasdaq_listed(raw,retrieved_at="2026-11-10T18:00:00Z")
  self.assertEqual(one,two);self.assertEqual(["AACGW","AAPL","BRK.B"],[x["normalized_symbol"] for x in one["rows"]]);self.assertEqual(3,one["source_freshness_max_calendar_days"])
  warrant=next(x for x in one["rows"] if x["raw_symbol"]=="AACGW");self.assertEqual(("D","N","N",100),(warrant["financial_status"],warrant["etf"],warrant["next_shares"],warrant["round_lot_size"]))
 def test_security_name_outer_spaces_normalize_with_raw_provenance(self):
  one=parse_nasdaq_listed(fixture(S,A),retrieved_at="2026-11-10T18:00:00Z");two=parse_nasdaq_listed(fixture(S,A),retrieved_at="2026-11-10T18:00:00Z");self.assertEqual(one,two)
  row=next(x for x in one["rows"] if x["raw_symbol"]=="SPACE");self.assertEqual("  Acme   Holdings  ",row["raw_security_name"]);self.assertEqual("Acme   Holdings",row["security_name"]);self.assertEqual("strip_outer_ascii_space_preserve_internal",row["security_name_normalization"])
 def test_security_name_empty_long_and_control_are_rejected(self):
  bad=[b"EMPTY|   |Q|N|N|100|N|N",b"LONG|"+b"X"*513+b"|Q|N|N|100|N|N",b"CTRL|Bad\tName|Q|N|N|100|N|N"]
  for row in bad:
   with self.subTest(row=row[:10]),self.assertRaisesRegex(NasdaqListedError,"^NASDAQ_SECURITY_NAME_INVALID$"):parse_nasdaq_listed(fixture(row),retrieved_at="2026-11-10T18:00:00Z")
 def test_raw_custody_preserves_security_name_spaces_byte_exact(self):
  raw=fixture(S)
  with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as td:
   root=Path(td);root.chmod(0o700);out=root/"run";result=acquire_nasdaq_listed(out,retrieved_at="2026-11-10T18:00:00Z",opener=lambda *a,**k:Response(raw))
   self.assertEqual(raw,(out/"nasdaqlisted.txt").read_bytes());self.assertEqual("  Acme   Holdings  ",result["parsed"]["rows"][0]["raw_security_name"]);self.assertEqual("Acme   Holdings",result["parsed"]["rows"][0]["security_name"])
 def test_freshness_exact_boundary_one_second_stale_and_old_2020(self):
  exact=parse_nasdaq_listed(fixture(A),retrieved_at="2026-11-13T17:30:00Z");self.assertEqual("2026-11-13T17:30:00Z",exact["source_freshness_deadline_utc"])
  with self.assertRaisesRegex(NasdaqListedError,"^NASDAQ_SOURCE_STALE$"):parse_nasdaq_listed(fixture(A),retrieved_at="2026-11-13T17:30:01Z")
  old=fixture(A,trailer=b"File Creation Time: 0102202012:30|||||||\r\n")
  with self.assertRaisesRegex(NasdaqListedError,"^NASDAQ_SOURCE_STALE$"):parse_nasdaq_listed(old,retrieved_at="2026-11-10T18:00:00Z")
 def test_calendar_day_freshness_handles_spring_and_fall_dst(self):
  spring=fixture(A,trailer=b"File Creation Time: 0306202612:30|||||||\r\n");result=parse_nasdaq_listed(spring,retrieved_at="2026-03-09T16:30:00Z");self.assertEqual("2026-03-09T16:30:00Z",result["source_freshness_deadline_utc"]);self.assertEqual(255600,result["source_age_seconds"])
  with self.assertRaisesRegex(NasdaqListedError,"^NASDAQ_SOURCE_STALE$"):parse_nasdaq_listed(spring,retrieved_at="2026-03-09T16:30:01Z")
  fall=fixture(A,trailer=b"File Creation Time: 1030202612:30|||||||\r\n");result=parse_nasdaq_listed(fall,retrieved_at="2026-11-02T17:30:00Z");self.assertEqual("2026-11-02T17:30:00Z",result["source_freshness_deadline_utc"]);self.assertEqual(262800,result["source_age_seconds"])
 def test_rejects_header_trailer_future_duplicate_and_malformed(self):
  cases=[(fixture(A).replace(b"Symbol|",b"Ticker|",1),"NASDAQ_HEADER_INVALID"),(fixture(A,trailer=b"bad|||||||\r\n"),"NASDAQ_TRAILER_INVALID"),(fixture(A,trailer=b"File Creation Time: 1111202612:30|||||||\r\n"),"NASDAQ_FILE_CREATION_IN_FUTURE"),(fixture(A,A),"NASDAQ_DUPLICATE_NORMALIZED_SYMBOL"),(fixture(b"BAD|too|few"),"NASDAQ_ROW_MALFORMED")]
  for raw,code in cases:
   with self.subTest(code=code),self.assertRaisesRegex(NasdaqListedError,"^"+code+"$"):parse_nasdaq_listed(raw,retrieved_at="2026-11-10T18:00:00Z")
 def test_acquisition_custody_proves_no_redirect_policy_and_no_overwrite(self):
  raw=fixture(A,B);calls=[];response=Response(raw)
  def opener(request,timeout):calls.append((request.full_url,request.method,timeout));return response
  with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as td:
   root=Path(td);root.chmod(0o700);out=root/"run";result=acquire_nasdaq_listed(out,retrieved_at="2026-11-10T18:00:00Z",opener=opener)
   self.assertEqual([(SOURCE_URL,"GET",20)],calls);self.assertEqual(raw,(out/"nasdaqlisted.txt").read_bytes());self.assertEqual(hashlib.sha256(raw).hexdigest(),result["custody"]["raw_file"]["sha256"])
   self.assertEqual(("reject_before_follow",0,MAX_SOURCE_AGE_CALENDAR_DAYS),(result["custody"]["redirect_policy"],result["custody"]["redirect_count"],result["custody"]["source_freshness_max_calendar_days"]));self.assertTrue(response.closed)
   with self.assertRaisesRegex(NasdaqListedError,"NASDAQ_OUTPUT_EXISTS_OR_INVALID"):acquire_nasdaq_listed(out,retrieved_at="2026-11-10T18:00:00Z",opener=opener)
   self.assertEqual(1,len(calls))
 def test_redirect_handler_refuses_follow_and_redirect_response_is_rejected(self):
  self.assertIsNone(_RejectRedirects().redirect_request(None,None,302,"Found",{},"https://example.com/x"))
  with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as td:
   root=Path(td);root.chmod(0o700);out=root/"run"
   with self.assertRaisesRegex(NasdaqListedError,"^NASDAQ_REDIRECT_REJECTED$"):acquire_nasdaq_listed(out,retrieved_at="2026-11-10T18:00:00Z",opener=lambda *a,**k:Response(fixture(A),status=302))
   self.assertFalse(out.exists())
 def test_url_drift_and_oversize_are_rejected_without_partial_directory(self):
  raw=fixture(A)
  for response,code in ((Response(raw,url="https://example.com/x"),"NASDAQ_REDIRECT_OR_URL_DRIFT"),(Response(b"x"*(8*1024*1024+1),headers={"Content-Type":"text/plain"}),"NASDAQ_RAW_SIZE_INVALID")):
   with self.subTest(code=code),tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as td:
    root=Path(td);root.chmod(0o700);out=root/"run"
    with self.assertRaisesRegex(NasdaqListedError,"^"+code+"$"):acquire_nasdaq_listed(out,retrieved_at="2026-11-10T18:00:00Z",opener=lambda *a,r=response,**k:r)
    self.assertFalse(out.exists())
if __name__=="__main__":unittest.main()
