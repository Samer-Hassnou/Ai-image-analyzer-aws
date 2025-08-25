import os, json, base64, uuid, logging, mimetypes, re
from typing import Tuple, Dict, Any, List
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3          = boto3.client("s3")
rekognition = boto3.client("rekognition")
dynamo      = boto3.client("dynamodb")
sts         = boto3.client("sts")

BUCKET     = os.environ.get("BUCKET_NAME")
PREFIX     = os.environ.get("UPLOAD_PREFIX", "uploads/")
MIN_CONF   = float(os.environ.get("DEFAULT_MIN_CONFIDENCE", "55"))
MAX_LABELS = int(os.environ.get("DEFAULT_MAX_LABELS", "100"))

QUOTA_TABLE = os.environ.get("QUOTA_TABLE")
QUOTA_LIMIT = int(os.environ.get("QUOTA_LIMIT", "3"))
FEATURE_QUOTA_ENABLED = os.environ.get("FEATURE_QUOTA_ENABLED", "true").lower() in ("1","true","yes")

try:
    THIS_ACCOUNT_ID = sts.get_caller_identity()["Account"]
except Exception:
    THIS_ACCOUNT_ID = None

ARN_ACC_RE = re.compile(r"arn:aws:(?:iam|sts)::(\d{12}):")

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "content-type,x-client-id,authorization,x-amz-date,x-amz-security-token,x-amz-content-sha256",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}

# ------------------------- Helpers -------------------------
def _resp(status: int, body: Any, headers: Dict[str, str] = None):
    h = {"content-type": "application/json"}
    h.update(CORS_HEADERS)
    if headers: h.update(headers)
    return {"statusCode": status, "headers": h, "body": json.dumps(body, ensure_ascii=False)}

def _parse_event(event: Dict[str, Any]) -> Tuple[str,str,Dict[str,Any],bool]:
    path = event.get("rawPath") or event.get("path") or "/"
    method = (event.get("requestContext", {}).get("http", {}).get("method")
              or event.get("httpMethod") or "GET").upper()
    body = event.get("body"); is_b64 = bool(event.get("isBase64Encoded", False))
    data = {}
    if body:
        try:
            if is_b64:
                body = base64.b64decode(body)
                data = json.loads(body.decode("utf-8"))
            else:
                data = json.loads(body)
        except Exception as e:
            logger.warning("Failed to parse body JSON: %s", e)
    return (path or "/"), method, data, is_b64

def _guess_content_type(filename: str) -> str:
    ctype, _ = mimetypes.guess_type(filename or "")
    return ctype or "application/octet-stream"

def _sanitize_prefix(p: str) -> str:
    return p if (p and p.endswith("/")) else ((p or "") + "/")

def _put_object_to_s3(bucket: str, key: str, raw_bytes: bytes, content_type: str):
    s3.put_object(Bucket=bucket, Key=key, Body=raw_bytes, ContentType=content_type, ServerSideEncryption="AES256")

def _source_ip(event) -> str:
    try:
        return event["requestContext"]["http"]["sourceIp"]
    except Exception:
        hdr = (event.get("headers") or {})
        return (hdr.get("x-forwarded-for") or "0.0.0.0").split(",")[0].strip()

def _headers_lower(event) -> Dict[str,str]:
    h = event.get("headers") or {}
    return { (k or "").lower(): v for k,v in h.items() }

def _client_id(event) -> str:
    hl = _headers_lower(event)
    return hl.get("x-client-id") or f"ip:{_source_ip(event)}"

# ------------------------- Quota -------------------------
def _today_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _next_midnight_epoch_utc() -> int:
    now = datetime.now(timezone.utc)
    tomorrow0 = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(tomorrow0.timestamp())

def enforce_quota(event) -> int:
    if not FEATURE_QUOTA_ENABLED or not QUOTA_TABLE:
        return 0
    user_id = _client_id(event); day = _today_utc_str()
    pk = f"user#{user_id}"; sk = day; ttl = _next_midnight_epoch_utc()
    try:
        res = dynamo.update_item(
            TableName=QUOTA_TABLE,
            Key={"pk":{"S":pk}, "sk":{"S":sk}},
            UpdateExpression="SET cnt = if_not_exists(cnt, :z) + :one, expires = :ttl",
            ConditionExpression="attribute_not_exists(cnt) OR cnt < :lim",
            ExpressionAttributeValues={
                ":z":{"N":"0"}, ":one":{"N":"1"}, ":lim":{"N":str(QUOTA_LIMIT)}, ":ttl":{"N":str(ttl)}
            },
            ReturnValues="ALL_NEW"
        )
        return int(res["Attributes"]["cnt"]["N"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            resp = _resp(429, {"message": f"Daily limit reached ({QUOTA_LIMIT}/day). Try again tomorrow."},
                         headers={"x-ratelimit-limit": str(QUOTA_LIMIT), "x-ratelimit-remaining": "0"})
            raise RuntimeError(json.dumps(resp))
        raise

# ------------------------- Rekognition: Labels -------------------------
def _detect_labels_by_s3(bucket: str, key: str) -> List[Dict[str, Any]]:
    logger.info("DetectLabels: s3://%s/%s", bucket, key)
    resp = rekognition.detect_labels(
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        MaxLabels=MAX_LABELS,
        MinConfidence=MIN_CONF,
    )
    out = []
    for lab in resp.get("Labels", []):
        out.append({
            "Name": lab.get("Name"),
            "Confidence": float(lab.get("Confidence", 0)),
            "Parents": [p.get("Name") for p in lab.get("Parents", []) if p.get("Name")],
        })
    return out

# ------------------------- Rekognition: Text (LINES only, deduped) -------------------------
def _norm_text(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip().lower()
    return s

def _iou(bb1: Dict[str, float], bb2: Dict[str, float]) -> float:

    x1, y1 = bb1["Left"], bb1["Top"]
    x2, y2 = x1 + bb1["Width"], y1 + bb1["Height"]
    a1, b1 = bb2["Left"], bb2["Top"]
    a2, b2 = a1 + bb2["Width"], b1 + bb2["Height"]
    inter_x1, inter_y1 = max(x1, a1), max(y1, b1)
    inter_x2, inter_y2 = min(x2, a2), min(y2, b2)
    iw, ih = max(0.0, inter_x2 - inter_x1), max(0.0, inter_y2 - inter_y1)
    inter = iw * ih
    if inter == 0: return 0.0
    area1 = (x2 - x1) * (y2 - y1)
    area2 = (a2 - a1) * (b2 - b1)
    return inter / (area1 + area2 - inter + 1e-9)

def _group_words_into_lines(words: List[Dict[str,Any]]) -> List[Dict[str,Any]]:
   
    if not words: return []
  
    def center_y(bb): return bb["Top"] + bb["Height"]/2
    words.sort(key=lambda w: (round(center_y(w["Geometry"]["BoundingBox"])*100), w["Geometry"]["BoundingBox"]["Left"]))

    rows: Dict[int, List[Dict[str,Any]]] = {}
    band = 0.04  
    for w in words:
        bb = w["Geometry"]["BoundingBox"]
        r  = int(center_y(bb) / band)
        rows.setdefault(r, []).append(w)

    lines = []
    for r, ws in sorted(rows.items(), key=lambda kv: kv[0]):
        ws.sort(key=lambda w: w["Geometry"]["BoundingBox"]["Left"])
        text = " ".join(w["DetectedText"] for w in ws)
        conf = sum(float(w["Confidence"]) for w in ws) / max(1,len(ws))
        # اجمع الصندوق
        lefts  = [w["Geometry"]["BoundingBox"]["Left"] for w in ws]
        tops   = [w["Geometry"]["BoundingBox"]["Top"] for w in ws]
        rights = [l + w["Geometry"]["BoundingBox"]["Width"] for l,w in zip(lefts, ws)]
        bots   = [t + w["Geometry"]["BoundingBox"]["Height"] for t,w in zip(tops, ws)]
        bb = {
            "Left":   min(lefts), "Top":  min(tops),
            "Width":  max(rights) - min(lefts),
            "Height": max(bots)   - min(tops)
        }
        lines.append({"Type":"LINE","DetectedText":text,"Confidence":conf,"Geometry":{"BoundingBox":bb}})
    return lines

def _detect_text_lines_by_s3(bucket: str, key: str, min_conf: float) -> List[Dict[str,Any]]:
    logger.info("DetectText: s3://%s/%s", bucket, key)
    resp = rekognition.detect_text(Image={"S3Object":{"Bucket":bucket,"Name":key}})
    dets = resp.get("TextDetections", []) or []

    lines = [d for d in dets if d.get("Type") == "LINE" and float(d.get("Confidence",0)) >= min_conf]

    if not lines:
        words = [d for d in dets if d.get("Type") == "WORD" and float(d.get("Confidence",0)) >= min_conf]
        lines = _group_words_into_lines(words)  
        built = []
        for l in lines:
            bb = (l.get("Geometry") or {}).get("BoundingBox") or {}
            built.append({
                "DetectedText": l.get("DetectedText",""),
                "Confidence": float(l.get("Confidence",0)),
                "Geometry": {"BoundingBox": {"Left":bb.get("Left",0.0), "Top":bb.get("Top",0.0),
                                             "Width":bb.get("Width",0.0), "Height":bb.get("Height",0.0)}}
            })
        lines = built

    uniq: List[Dict[str,Any]] = []
    def _norm_text(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip().lower()

    def _iou(bb1: Dict[str, float], bb2: Dict[str, float]) -> float:
        x1, y1 = bb1["Left"], bb1["Top"]
        x2, y2 = x1 + bb1["Width"], y1 + bb1["Height"]
        a1, b1 = bb2["Left"], bb2["Top"]
        a2, b2 = a1 + bb2["Width"], b1 + bb2["Height"]
        inter_x1, inter_y1 = max(x1, a1), max(y1, b1)
        inter_x2, inter_y2 = min(x2, a2), min(y2, b2)
        iw, ih = max(0.0, inter_x2 - inter_x1), max(0.0, inter_y2 - inter_y1)
        inter = iw * ih
        if inter == 0: return 0.0
        area1 = (x2 - x1) * (y2 - y1)
        area2 = (a2 - a1) * (b2 - b1)
        return inter / (area1 + area2 - inter + 1e-9)

    for l in lines:
        txt = l.get("DetectedText","")
        bb  = (l.get("Geometry") or {}).get("BoundingBox") or {"Left":0,"Top":0,"Width":0,"Height":0}
        txtn = _norm_text(txt)
        is_dup = False
        for u in uniq:
            if _norm_text(u["DetectedText"]) == txtn and _iou(bb, u["Box"]) > 0.5:
                is_dup = True
                break
        if not is_dup:
            uniq.append({
                "DetectedText": txt,
                "Confidence": float(l.get("Confidence",0)),
                "Box": {"Left":bb["Left"], "Top":bb["Top"], "Width":bb["Width"], "Height":bb["Height"]}
            })

    return uniq

# ------------------------- IAM helpers -------------------------
def _caller_account_from_event(event) -> str | None:
    rc = event.get("requestContext") or {}
    try:
        iam = (rc.get("authorizer") or {}).get("iam") or {}
        if iam.get("accountId"): return str(iam["accountId"])
        if iam.get("userArn"):
            m = ARN_ACC_RE.search(iam["userArn"])
            if m: return m.group(1)
    except Exception:
        pass
    try:
        user_arn = (rc.get("identity") or {}).get("userArn")
        if user_arn:
            m = ARN_ACC_RE.search(user_arn); 
            if m: return m.group(1)
    except Exception:
        pass
    return None

def _is_same_account_admin_request(event) -> bool:
    path = (event.get("rawPath") or event.get("path") or "")
    if not path.endswith("/admin/analyze"): return False
    if not THIS_ACCOUNT_ID: return False
    caller_acc = _caller_account_from_event(event)
    return caller_acc == THIS_ACCOUNT_ID

# ------------------------- Core -------------------------
def _process_analyze(data: Dict[str, Any]) -> Dict[str, Any]:
    if not BUCKET:
        return _resp(500, {"ok": False, "message": "Missing BUCKET_NAME env"})

    b64 = data.get("content_base64")
    filename = (data.get("filename") or "").strip() or "image.jpg"
    if not b64:
        return _resp(400, {"ok": False, "message": "content_base64 is required"})

    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception as e:
        logger.exception("Invalid base64: %s", e)
        return _resp(400, {"ok": False, "message": "Invalid base64 payload"})

    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    key = f"{_sanitize_prefix(PREFIX)}{uuid.uuid4().hex}{ext}"

    content_type = _guess_content_type(filename)
    if content_type == "application/octet-stream":
        if ext in (".jpg", ".jpeg"): content_type = "image/jpeg"
        elif ext == ".png":          content_type = "image/png"

    mode = (data.get("mode") or "labels").lower()
    min_conf = float(data.get("min_confidence") or MIN_CONF)

    try:
        _put_object_to_s3(BUCKET, key, raw, content_type)
        logger.info("Uploaded s3://%s/%s", BUCKET, key)

        if mode == "text":
            texts = _detect_text_lines_by_s3(BUCKET, key, min_conf)
            return _resp(200, {"stored": f"s3://{BUCKET}/{key}", "mode":"text", "texts": texts})
        else:
            labels = _detect_labels_by_s3(BUCKET, key)
            return _resp(200, {"stored": f"s3://{BUCKET}/{key}", "mode":"labels", "labels": labels})

    except ClientError as ce:
        logger.exception("AWS error: %s", ce)
        return _resp(502, {"ok": False, "message": "AWS error", "detail": str(ce)})
    except Exception as e:
        logger.exception("Unhandled: %s", e)
        return _resp(500, {"ok": False, "message": "Unhandled", "detail": str(e)})

# ------------------------- Handler -------------------------
def lambda_handler(event, context):
    try:
        path, method, data, _ = _parse_event(event)
        path = (path or "/").rstrip("/") or "/"
        logger.info("Request %s %s", method, path)

        if method == "OPTIONS":
            return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

        if path == "/health" and method == "GET":
            return _resp(200, {"ok": True, "message": "API ↔ Lambda working", "bucket": BUCKET,
                               "quota_enabled": FEATURE_QUOTA_ENABLED})

        if path == "/admin/analyze" and method == "POST":
            bypass = _is_same_account_admin_request(event)
            if not bypass:
                try: _ = enforce_quota(event)
                except RuntimeError as rex: return json.loads(str(rex))
            res = _process_analyze(data)
            if bypass and isinstance(res, dict):
                res.setdefault("headers", {}); res["headers"]["x-quota-bypass"] = "same-account"
            return res

        if path == "/analyze" and method == "POST":
            try: new_cnt = enforce_quota(event)
            except RuntimeError as rex: return json.loads(str(rex))
            res = _process_analyze(data)
            if isinstance(res, dict):
                res.setdefault("headers", {})
                res["headers"]["x-ratelimit-limit"] = str(QUOTA_LIMIT) if FEATURE_QUOTA_ENABLED else "disabled"
                res["headers"]["x-ratelimit-remaining"] = str(max(0, QUOTA_LIMIT - (new_cnt or 0))) if FEATURE_QUOTA_ENABLED else "disabled"
            return res

        return _resp(404, {"ok": False, "message": "Not Found"})
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        return _resp(500, {"ok": False, "message": "Fatal", "detail": str(e)})
