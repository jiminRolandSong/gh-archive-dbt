import json
import os
import io
import logging
import boto3
import requests
import snowflake.connector
from datetime import datetime, timedelta, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET           = os.environ["S3_BUCKET"]
SNOWFLAKE_ACCOUNT   = os.environ["SNOWFLAKE_ACCOUNT"]
SNOWFLAKE_USER      = os.environ["SNOWFLAKE_USER"]
SNOWFLAKE_PASSWORD  = os.environ["SNOWFLAKE_PASSWORD"]

CHUNK_SIZE = 10 * 1024 * 1024  # 10MB


def resolve_hour(event):
    if "target_hour" in event:
        return event["target_hour"]
    target = datetime.now(timezone.utc) - timedelta(hours=1)
    return f"{target.strftime('%Y-%m-%d')}-{target.hour}"


def build_s3_key(hour_str):
    date_str, hour = hour_str.rsplit("-", 1)
    year, month, day = date_str.split("-")
    return f"raw/year={year}/month={month}/day={day}/hour={hour.zfill(2)}/{hour_str}.json.gz"


def stream_to_s3(hour_str, s3):
    url = f"https://data.gharchive.org/{hour_str}.json.gz"
    s3_key = build_s3_key(hour_str)
    logger.info(f"Fetching {url} → s3://{S3_BUCKET}/{s3_key}")

    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()

    mpu = s3.create_multipart_upload(Bucket=S3_BUCKET, Key=s3_key)
    upload_id = mpu["UploadId"]
    parts, part_num, buf, total = [], 1, io.BytesIO(), 0

    try:
        for chunk in resp.iter_content(chunk_size=5 * 1024 * 1024):
            if not chunk:
                continue
            buf.write(chunk)
            total += len(chunk)
            if buf.tell() >= CHUNK_SIZE:
                buf.seek(0)
                part = s3.upload_part(Bucket=S3_BUCKET, Key=s3_key,
                                      PartNumber=part_num, UploadId=upload_id, Body=buf.read())
                parts.append({"PartNumber": part_num, "ETag": part["ETag"]})
                part_num += 1
                buf = io.BytesIO()

        if buf.tell() > 0:
            buf.seek(0)
            part = s3.upload_part(Bucket=S3_BUCKET, Key=s3_key,
                                  PartNumber=part_num, UploadId=upload_id, Body=buf.read())
            parts.append({"PartNumber": part_num, "ETag": part["ETag"]})

        s3.complete_multipart_upload(Bucket=S3_BUCKET, Key=s3_key,
                                     UploadId=upload_id, MultipartUpload={"Parts": parts})
        logger.info(f"S3 upload done: {total:,} bytes")
        return s3_key, total

    except Exception:
        s3.abort_multipart_upload(Bucket=S3_BUCKET, Key=s3_key, UploadId=upload_id)
        raise


def copy_into_snowflake(s3_key):
    conn = snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT,
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        database="GH_ARCHIVE",
        schema="RAW",
        warehouse="COMPUTE_WH",
        role="TRANSFORMER",
    )
    try:
        cur = conn.cursor()
        stage_path = s3_key.removeprefix("raw/")
        sql = f"""
        COPY INTO GH_ARCHIVE.RAW.RAW_EVENTS (id, type, actor, repo, payload, created_at)
        FROM (
            SELECT
                $1:id::STRING,
                $1:type::STRING,
                $1:actor::VARIANT,
                $1:repo::VARIANT,
                $1:payload::VARIANT,
                $1:created_at::TIMESTAMP_NTZ
            FROM @GH_ARCHIVE.RAW.GH_ARCHIVE_STAGE/{stage_path}
        )
        FILE_FORMAT = (TYPE='JSON' COMPRESSION='GZIP' STRIP_OUTER_ARRAY=FALSE IGNORE_UTF8_ERRORS=TRUE)
        ON_ERROR  = 'CONTINUE'
        FORCE     = FALSE
        PURGE     = FALSE;
        """
        cur.execute(sql)
        rows = cur.fetchall()
        if not rows:
            return {"rows_loaded": 0, "status": "ALREADY_LOADED"}
        loaded = sum(r[3] or 0 for r in rows if len(r) > 3)
        errors = sum(r[5] or 0 for r in rows if len(r) > 5)
        logger.info(f"COPY INTO done: loaded={loaded:,}, errors={errors}")
        return {"rows_loaded": loaded, "errors_seen": errors, "status": "SUCCESS"}
    finally:
        conn.close()


def lambda_handler(event, context):
    hour_str = resolve_hour(event)
    logger.info(f"Processing hour: {hour_str}")
    s3 = boto3.client("s3")
    s3_key, bytes_up = stream_to_s3(hour_str, s3)
    sf = copy_into_snowflake(s3_key)
    return {"hour": hour_str, "bytes_uploaded": bytes_up, **sf}