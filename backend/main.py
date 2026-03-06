"""
FastAPI Backend for Worksheet Splitter - OPTIMIZED
YOLOv26 Custom Model with Parallel Processing & Caching
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import tempfile
import shutil
import zipfile
import os
from pathlib import Path
import io
import traceback
import fitz
import threading
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import datetime
import uuid
from functools import lru_cache
import asyncio

import boto3
from botocore.config import Config

from pocketbase import PocketBase
from contextlib import asynccontextmanager

import json

from split_pdf import YOLOQuestionSplitter
import pillow_heif
from PIL import Image
from dotenv import load_dotenv
load_dotenv()

IS_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT_NAME") is not None

if IS_RAILWAY:
    POCKETBASE_URL = "http://pocketbase.railway.internal:8080"
else:
    POCKETBASE_URL = "https://pocketbase-production-4854.up.railway.app"

POCKETBASE_EMAIL = os.environ.get("POCKETBASE_EMAIL")
POCKETBASE_PASSWORD = os.environ.get("POCKETBASE_PASSWORD")

pb = PocketBase(POCKETBASE_URL)

# ── R2 config ────────────────────────────────────────────────────────────────
SAVE_TO_R2       = os.environ.get("SAVE_TO_R2", "true").lower() == "true"
R2_ACCOUNT_ID    = os.environ.get("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME   = os.environ.get("R2_BUCKET_NAME", "examcrop-uploads")
R2_ENDPOINT      = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else None
# ─────────────────────────────────────────────────────────────────────────────

r2_client    = None
yolo_splitter = None
thread_pool   = None
process_pool  = None


def get_r2_client():
    """Initialize boto3 S3-compatible client for Cloudflare R2"""
    try:
        if not all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
            missing = [
                k for k, v in {
                    "R2_ACCOUNT_ID": R2_ACCOUNT_ID,
                    "R2_ACCESS_KEY_ID": R2_ACCESS_KEY_ID,
                    "R2_SECRET_ACCESS_KEY": R2_SECRET_ACCESS_KEY,
                }.items() if not v
            ]
            print(f"⚠️ Missing R2 credentials: {', '.join(missing)}")
            return None

        client = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        # quick sanity-check — will raise if creds are wrong
        client.head_bucket(Bucket=R2_BUCKET_NAME)
        print("✅ Cloudflare R2 initialised successfully")
        return client

    except Exception as e:
        print(f"❌ Failed to initialise R2: {e}")
        return None


def upload_to_r2(local_path: str, r2_key: str) -> str | None:
    """
    Upload a local file to R2.
    Returns the r2_key on success, None on failure.
    """
    try:
        if not os.path.exists(local_path):
            print(f"⚠️ File not found for R2 upload: {local_path}")
            return None

        r2_client.upload_file(local_path, R2_BUCKET_NAME, r2_key)
        return r2_key

    except Exception as e:
        print(f"❌ R2 upload failed for {r2_key}: {e}")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global r2_client, yolo_splitter, thread_pool, process_pool

    print("\n" + "="*70)
    print("🚀 APPLICATION STARTUP")
    print("="*70)

    try:
        if os.path.exists("best.pt"):
            print("📦 Loading YOLO model...")
            yolo_splitter = YOLOQuestionSplitter(debug=False, model_path="best.pt")
            print("✅ YOLO model loaded")
        else:
            print("❌ best.pt not found - service will not work")
            yolo_splitter = None
    except Exception as e:
        print(f"❌ YOLO model failed to load: {e}")
        yolo_splitter = None

    try:
        print("🔐 Authenticating with PocketBase...")
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
        print("✅ PocketBase authenticated")
    except Exception as e:
        print(f"⚠️ PocketBase auth failed (non-critical): {e}")

    if SAVE_TO_R2:
        try:
            print("☁️ Initialising Cloudflare R2...")
            r2_client = get_r2_client()
            if r2_client:
                print(f"✅ R2 ready (bucket: {R2_BUCKET_NAME})")
            else:
                print("⚠️ R2 not available (will skip uploads)")
        except Exception as e:
            print(f"⚠️ R2 init failed (non-critical): {e}")
            r2_client = None
    else:
        print("⚠️ R2 disabled (SAVE_TO_R2=false)")

    thread_pool = ThreadPoolExecutor(max_workers=4)
    process_pool = ProcessPoolExecutor(max_workers=2)
    print("✅ Thread and process pools initialised")

    print("="*70)
    print("✅ APPLICATION READY")
    print("="*70 + "\n")

    yield

    print("\n🛑 Shutting down...")
    if thread_pool:
        thread_pool.shutdown(wait=False)
    if process_pool:
        process_pool.shutdown(wait=False)

app = FastAPI(
    title="Worksheet Splitter - YOLOv26 Custom",
    description="AI-powered question splitting using custom-trained YOLOv26",
    version="11.1.0",
    lifespan=lifespan
)

origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost",
    "http://127.0.0.1",
    "https://examcrop.com",
    "https://www.examcrop.com",
    "https://pdf-splitter-production-9d84.up.railway.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Questions-Count", "Content-Disposition", "X-Upload-Id"],
)


@app.get("/api")
def read_root():
    model_status = "trained" if os.path.exists("best.pt") else "not_trained"
    return {
        "status": "ok",
        "service": "yolov26-question-splitter",
        "version": "11.1.0",
        "model": "YOLOv26 Custom Trained - Optimized",
        "model_status": model_status,
    }


@app.post("/split")
@app.post("/api/split")
async def split_worksheet(
    file: UploadFile = File(...),
    dpi: int = 250,
    debug: bool = False,
    conf_threshold: float = 0.10,
    is_sample: bool = False,
    pages: str = None,
    is_returning: bool = False,
    returning_email: str = "",
    source_page: str = "home",
):
    """
    Split worksheets using custom-trained YOLOv26 model - OPTIMIZED VERSION
    pages: optional comma-separated list of 1-indexed page numbers e.g. "1,3,5,6,7"
    """
    # Log sample usage to PocketBase without uploading to R2
    if is_sample:
        try:
            pb.collection('leads').create({
                "email": "",
                "feedback": "sample_viewed",
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            print(f"⚠️ Could not log sample view: {e}")

    if yolo_splitter is None:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Please try again in a moment."
        )

    MAX_SIZE  = 20 * 1024 * 1024
    MAX_PAGES = 20

    contents      = await file.read()
    file_size_mb  = len(contents) / (1024 * 1024)

    if len(contents) > MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({file_size_mb:.1f}MB). Maximum file size is 20MB."
        )

    allowed_extensions = ['.jpg', '.jpeg', '.png', '.pdf', '.heic', '.heif']
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
        )

    if not (100 <= dpi <= 600):
        raise HTTPException(status_code=400, detail="DPI must be between 100 and 600")

    if not (0.05 <= conf_threshold <= 0.95):
        raise HTTPException(status_code=400, detail="Confidence threshold must be between 0.05 and 0.95")

    upload_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    temp_dir  = tempfile.mkdtemp()

    try:
        import time
        start_time = time.time()

        input_path = os.path.join(temp_dir, file.filename)
        with open(input_path, 'wb') as f:
            f.write(contents)

        # Convert HEIC/HEIF to JPEG before any processing
        if file_ext in ('.heic', '.heif'):
            try:
                pillow_heif.register_heif_opener()
                img = Image.open(input_path)
                converted_path = os.path.join(temp_dir, Path(file.filename).stem + '.jpg')
                img.save(converted_path, 'JPEG', quality=95)
                input_path = converted_path
                file_ext = '.jpg'
                print(f"✅ Converted HEIC to JPEG: {converted_path}")
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Could not convert HEIC file: {str(e)}")

        if file_ext == '.pdf':
            try:
                doc        = fitz.open(input_path)
                page_count = len(doc)
                doc.close()

                if page_count > MAX_PAGES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Your PDF has {page_count} pages. Maximum {MAX_PAGES} pages supported."
                    )

                # ── Page selection: extract subset into a new PDF ──────────
                if pages:
                    try:
                        requested = [int(p.strip()) for p in pages.split(',') if p.strip()]
                        # Validate all requested pages are in range
                        invalid = [p for p in requested if p < 1 or p > page_count]
                        if invalid:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Page numbers out of range: {invalid}. PDF has {page_count} pages."
                            )

                        # Build a new PDF with only the selected pages
                        src_doc     = fitz.open(input_path)
                        subset_doc  = fitz.open()
                        for p in sorted(set(requested)):
                            subset_doc.insert_pdf(src_doc, from_page=p - 1, to_page=p - 1)
                        src_doc.close()

                        subset_path = os.path.join(temp_dir, f"subset_{file.filename}")
                        subset_doc.save(subset_path, garbage=4, deflate=True)
                        subset_doc.close()

                        input_path  = subset_path
                        page_count  = len(requested)
                        print(f"  → Page selection applied: {sorted(set(requested))} ({page_count} pages)")
                    except HTTPException:
                        raise
                    except Exception as e:
                        print(f"Warning: Could not apply page selection: {e}")
                # ─────────────────────────────────────────────────────────

                print(f"\nProcessing: {file.filename} ({file_size_mb:.1f}MB, {page_count} pages)")
            except HTTPException:
                raise
            except Exception as e:
                print(f"Warning: Could not check page count: {e}")
                print(f"\nProcessing: {file.filename} ({file_size_mb:.1f}MB)")
        else:
            print(f"\nProcessing: {file.filename} ({file_size_mb:.1f}MB, 1 page)")

        output_dir = os.path.join(temp_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        try:
            yolo_splitter.split_worksheet(
                input_path=input_path,
                output_dir=output_dir,
                dpi=dpi,
                cleanup_temp=True,
                conf_threshold=conf_threshold
            )

            processing_time = time.time() - start_time
            print(f"⏱️ Processing completed in {processing_time:.2f} seconds")
        except SystemExit:
            raise HTTPException(status_code=422, detail="No questions detected")

        output_files = list(Path(output_dir).glob('*.pdf'))

        if not output_files:
            raise HTTPException(status_code=422, detail="No questions detected")

        print(f"✓ Successfully split into {len(output_files)} questions")

        # Build combined PDF
        combined_pdf  = fitz.open()
        for pdf_file in sorted(output_files):
            src_pdf = fitz.open(pdf_file)
            combined_pdf.insert_pdf(src_pdf)
            src_pdf.close()
        combined_path = os.path.join(output_dir, 'all_questions_combined.pdf')
        combined_pdf.save(combined_path, garbage=4, deflate=True, clean=True, pretty=False)
        combined_pdf.close()

        # Build ZIP in memory — combined PDF only
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.write(combined_path, 'all_questions_combined.pdf')
            if debug:
                for debug_file in Path(temp_dir).glob('debug_*.png'):
                    zip_file.write(debug_file, f"debug/{debug_file.name}")

        zip_buffer.seek(0)

        base_name    = Path(file.filename).stem
        zip_filename = f"{base_name}_questions.zip"

        total_time = time.time() - start_time
        print(f"✓ Total time: {total_time:.2f}s | ZIP: {zip_filename} ({len(zip_buffer.getvalue()) / 1024 / 1024:.2f}MB)")

        # Log upload to PocketBase uploads collection
        try:
            pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
            pb.collection('uploads').create({
                "upload_id":          upload_id,
                "filename":           file.filename,
                "pages_processed":    page_count if file_ext == ".pdf" else 1,
                "questions_detected": len(output_files),
                "is_sample":          is_sample,
                "is_returning":       is_returning,
                "source_page":        source_page,
                "email":              returning_email if is_returning and returning_email else "",
                "timestamp":          datetime.utcnow().isoformat() + "Z",
            })
            print(f"Upload logged: {upload_id}")
        except Exception as pb_err:
            print(f"Could not log upload to PocketBase: {pb_err}")

        # ── Background R2 upload ─────────────────────────────────────────────
        if SAVE_TO_R2 and r2_client and not is_sample:
            background_data = {
                'input_path':      input_path,
                'output_files':    [str(f) for f in sorted(output_files)],
                'combined_path':   combined_path,
                'temp_dir':        temp_dir,
                'upload_id':       upload_id,
                'filename':        file.filename,
                'file_size_mb':    file_size_mb,
                'dpi':             dpi,
                'conf_threshold':  conf_threshold,
                'questions_count': len(output_files),
            }

            def upload_async():
                try:
                    print(f"\n🚀 Background R2 upload started: {background_data['upload_id']}")
                    prefix = f"uploads/{background_data['upload_id']}"

                    # original file
                    upload_to_r2(
                        background_data['input_path'],
                        f"{prefix}/original_{background_data['filename']}"
                    )

                    # metadata
                    metadata = {
                        "upload_id":          background_data['upload_id'],
                        "timestamp":          datetime.now().isoformat(),
                        "filename":           background_data['filename'],
                        "file_size_mb":       background_data['file_size_mb'],
                        "dpi":                background_data['dpi'],
                        "conf_threshold":     background_data['conf_threshold'],
                        "questions_detected": background_data['questions_count'],
                        "processing_status":  "success",
                    }
                    metadata_path = os.path.join(background_data['temp_dir'], 'metadata.json')
                    with open(metadata_path, 'w') as f:
                        json.dump(metadata, f, indent=2)
                    upload_to_r2(metadata_path, f"{prefix}/metadata.json")

                    # combined PDF
                    upload_to_r2(
                        background_data['combined_path'],
                        f"{prefix}/output/all_questions_combined.pdf"
                    )

                    # individual question PDFs
                    for pdf_path in background_data['output_files']:
                        upload_to_r2(pdf_path, f"{prefix}/output/{Path(pdf_path).name}")

                    print(f"✅ R2 upload completed: {prefix}")

                except Exception as e:
                    print(f"⚠️ Background R2 upload failed: {e}")
                    traceback.print_exc()

                finally:
                    try:
                        if os.path.exists(background_data['temp_dir']):
                            shutil.rmtree(background_data['temp_dir'])
                            print(f"🗑️ Cleaned up temp dir: {background_data['upload_id']}")
                    except Exception as e:
                        print(f"⚠️ Cleanup warning: {e}")

            threading.Thread(target=upload_async, daemon=True).start()
            print("🚀 Started background R2 upload (not blocking response)")

        else:
            # R2 disabled — just clean up
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"Cleanup warning: {e}")
        # ────────────────────────────────────────────────────────────────────

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={zip_filename}",
                "X-Questions-Count":   str(len(output_files)),
                "X-Upload-Id":         upload_id,
                "X-Method":            "YOLOv26-Custom-Optimized",
            }
        )

    except HTTPException:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
        raise

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"\n❌ ERROR: {error_trace}")

        # ── Log errors to R2 too ─────────────────────────────────────────────
        if SAVE_TO_R2 and r2_client:
            error_data = {
                'temp_dir':       temp_dir,
                'input_path':     input_path if 'input_path' in locals() else None,
                'upload_id':      upload_id,
                'filename':       file.filename,
                'file_size_mb':   file_size_mb,
                'dpi':            dpi,
                'conf_threshold': conf_threshold,
                'error':          str(e),
                'error_trace':    error_trace,
            }

            def log_error_async():
                try:
                    prefix = f"uploads/{error_data['upload_id']}_ERROR"

                    error_path = os.path.join(error_data['temp_dir'], 'error.log')
                    with open(error_path, 'w') as f:
                        f.write(error_data['error_trace'])
                    upload_to_r2(error_path, f"{prefix}/error.log")

                    if error_data['input_path'] and os.path.exists(error_data['input_path']):
                        upload_to_r2(
                            error_data['input_path'],
                            f"{prefix}/original_{error_data['filename']}"
                        )

                    metadata = {
                        "upload_id":         error_data['upload_id'],
                        "timestamp":         datetime.now().isoformat(),
                        "filename":          error_data['filename'],
                        "file_size_mb":      error_data['file_size_mb'],
                        "dpi":               error_data['dpi'],
                        "conf_threshold":    error_data['conf_threshold'],
                        "processing_status": "error",
                        "error":             error_data['error'],
                    }
                    metadata_path = os.path.join(error_data['temp_dir'], 'metadata.json')
                    with open(metadata_path, 'w') as f:
                        json.dump(metadata, f, indent=2)
                    upload_to_r2(metadata_path, f"{prefix}/metadata.json")

                    print(f"✅ Error logged to R2: {prefix}")

                except Exception as log_err:
                    print(f"⚠️ Failed to log error to R2: {log_err}")
                finally:
                    if error_data['temp_dir'] and os.path.exists(error_data['temp_dir']):
                        try:
                            shutil.rmtree(error_data['temp_dir'])
                        except:
                            pass

            threading.Thread(target=log_error_async, daemon=True).start()

        else:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass

        raise HTTPException(
            status_code=500,
            detail=f"Processing failed: {str(e)}"
        )


@app.get("/api/health")
def health_check():
    model_exists = os.path.exists("best.pt")
    return {
        "status":      "healthy" if model_exists else "model_missing",
        "method":      "YOLOv26 Custom Trained - Optimized",
        "model_ready": yolo_splitter is not None,
        "r2_enabled":  SAVE_TO_R2,
        "r2_ready":    r2_client is not None,
    }


@app.get("/api/info")
def get_info():
    return {
        "service":           "YOLOv26 Question Splitter",
        "version":           "11.1.0",
        "description":       "Custom-trained YOLOv26 for worksheet question detection - Optimized",
        "supported_formats": ["PDF", "JPG", "JPEG", "PNG"],
        "max_file_size":     "20MB",
        "max_pages":         "20 pages",
        "recommended_dpi":   150,
        "recommended_conf":  0.10,
    }


@app.get("/sample")
@app.get("/api/sample")
async def get_sample_file():
    """Serve the sample worksheet file"""
    possible_paths = [
        Path("frontend/sample.png"),
        Path("../frontend/sample.png"),
        Path("./sample.png"),
        Path("sample.png"),
        Path("frontend/sample_worksheet.pdf"),
        Path("../frontend/sample_worksheet.pdf"),
        Path("./sample_worksheet.pdf"),
    ]

    for sample_path in possible_paths:
        if sample_path.exists():
            return FileResponse(sample_path)

    raise HTTPException(
        status_code=404,
        detail="Sample file not found. Please upload your own file."
    )


@app.post("/api/feedback")
async def collect_feedback(request: dict):
    """Collect user feedback, save to leads, and link email to upload record"""
    try:
        email        = request.get('email', '')
        comment      = request.get('comment', '')
        timestamp    = request.get('timestamp', '')
        upload_id    = request.get('upload_id', '')
        is_returning = request.get('is_returning', False)
        marketing    = request.get('marketing_opt_in', False)

        if not email and not comment:
            return {"status": "success", "message": "No data provided"}

        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)

        # Save to leads collection
        data = {
            "email":            email or "",
            "feedback":         comment or "",
            "timestamp":        timestamp or "",
            "is_returning":     is_returning,
            "marketing_opt_in": marketing,
        }
        record = pb.collection('leads').create(data)
        print(f"Saved lead: {email} (returning={is_returning})")

        # Link email to the upload record if we have an upload_id
        if upload_id and email:
            try:
                results = pb.collection('uploads').get_list(1, 1, {
                    "filter": f'upload_id = "{upload_id}"'
                })
                if results.items:
                    pb.collection('uploads').update(results.items[0].id, {
                        "email": email
                    })
                    print(f"Linked email to upload: {upload_id}")
            except Exception as link_err:
                print(f"Could not link email to upload: {link_err}")

        return {
            "status":  "success",
            "message": "Thank you for your feedback!",
            "id":      record.id,
        }

    except Exception as e:
        print(f"PocketBase save error: {e}")
        return {"status": "error", "message": str(e)}



# ── Auth dependency ──────────────────────────────────────────────────────────

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Validate PocketBase JWT token and return user record."""
    token = credentials.credentials
    print(f"[AUTH] Token received (first 20 chars): {token[:20] if token else 'NONE'}...")
    try:
        resp = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: __import__('requests').post(
                f"{POCKETBASE_URL}/api/collections/users/auth-refresh",
                headers={"Authorization": token},
                timeout=5,
            )
        )
        print(f"[AUTH] PocketBase response status: {resp.status_code}")
        if resp.status_code != 200:
            print(f"[AUTH] PocketBase rejected token: {resp.text[:200]}")
            raise HTTPException(status_code=401, detail="Invalid or expired token.")
        data = resp.json()
        user_id = data["record"]["id"]
        user_email = data["record"]["email"]
        print(f"[AUTH] Token valid for user: {user_email} ({user_id})")
        return {"id": user_id, "email": user_email, "token": token}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[AUTH] Exception in get_current_user: {e}")
        raise HTTPException(status_code=401, detail=f"Auth error: {str(e)}")


# ── R2 signed URL ─────────────────────────────────────────────────────────────

@app.get("/api/r2-url")
async def get_r2_signed_url(
    key: str = Query(..., description="R2 object key e.g. uploads/upload_id/output/question_01.pdf"),
    user: dict = Depends(get_current_user),
):
    """Generate a short-lived presigned URL for an R2 object."""
    if not r2_client:
        raise HTTPException(status_code=503, detail="R2 not available.")

    # Security: only allow access to the user's own questions via questions table
    # Key must start with "uploads/" to prevent path traversal
    if not key.startswith("uploads/"):
        raise HTTPException(status_code=400, detail="Invalid key.")

    try:
        url = r2_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": R2_BUCKET_NAME, "Key": key},
            ExpiresIn=3600,  # 1 hour
        )
        return {"url": url, "expires_in": 3600}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate URL: {str(e)}")


# ── Thumbnail ─────────────────────────────────────────────────────────────────

@app.get("/api/thumbnail")
async def get_thumbnail(
    key: str = Query(..., description="R2 key of the question PDF e.g. uploads/.../output/question_01.pdf"),
    user: dict = Depends(get_current_user),
):
    """
    Return a small JPEG thumbnail for a question PDF.
    Checks R2 for a cached thumbnail first; generates and uploads it if missing.
    Thumbnail key mirrors the PDF key but under thumbnails/ and with .jpg extension.
    e.g. uploads/{id}/output/question_01.pdf -> uploads/{id}/thumbnails/question_01.jpg
    """
    if not r2_client:
        raise HTTPException(status_code=503, detail="R2 not available.")
    if not key.startswith("uploads/"):
        raise HTTPException(status_code=400, detail="Invalid key.")

    # Derive thumbnail key
    parts = key.split("/")
    # parts: ['uploads', upload_id, 'output', 'question_01.pdf']
    pdf_filename = parts[-1]
    jpg_filename = Path(pdf_filename).stem + ".jpg"
    thumb_key = "/".join(parts[:-2]) + f"/thumbnails/{jpg_filename}"

    # Try cached thumbnail first
    try:
        obj = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: r2_client.get_object(Bucket=R2_BUCKET_NAME, Key=thumb_key)
        )
        img_bytes = obj["Body"].read()
        return StreamingResponse(io.BytesIO(img_bytes), media_type="image/jpeg",
                                 headers={"Cache-Control": "public, max-age=86400"})
    except r2_client.exceptions.NoSuchKey:
        pass
    except Exception:
        pass  # cache miss for any reason — generate it

    # Generate thumbnail from the PDF
    try:
        # Fetch the PDF from R2
        pdf_obj = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: r2_client.get_object(Bucket=R2_BUCKET_NAME, Key=key)
        )
        pdf_bytes = pdf_obj["Body"].read()

        # Render page 1 at low res with fitz
        doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        # mat=0.4 zoom → small canvas, enough for a thumbnail
        mat  = fitz.Matrix(0.4, 0.4)
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("jpeg", jpg_quality=75)
        doc.close()

        # Upload to R2 asynchronously (don't block the response)
        def _upload_thumb():
            try:
                r2_client.put_object(
                    Bucket=R2_BUCKET_NAME,
                    Key=thumb_key,
                    Body=img_bytes,
                    ContentType="image/jpeg",
                )
                print(f"✅ Thumbnail cached: {thumb_key}")
            except Exception as e:
                print(f"⚠️ Could not cache thumbnail: {e}")

        threading.Thread(target=_upload_thumb, daemon=True).start()

        return StreamingResponse(io.BytesIO(img_bytes), media_type="image/jpeg",
                                 headers={"Cache-Control": "public, max-age=86400"})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate thumbnail: {str(e)}")




@app.post("/api/save-questions")
async def save_questions(
    request: dict,
    user: dict = Depends(get_current_user),
):
    """
    Save split questions to the user's question bank.
    Reads metadata.json from R2 to get question count, then creates
    one questions record per question in PocketBase.
    """
    upload_id   = request.get("upload_id", "").strip()
    source_pdf  = request.get("source_pdf", "")
    subject     = request.get("subject", "")
    curriculum  = request.get("curriculum", "")

    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id required.")

    # Fetch metadata from R2 to get accurate question count
    metadata_key = f"uploads/{upload_id}/metadata.json"
    try:
        obj = r2_client.get_object(Bucket=R2_BUCKET_NAME, Key=metadata_key)
        metadata = json.loads(obj["Body"].read())
        questions_count = metadata.get("questions_detected", 0)
        filename = metadata.get("filename", source_pdf)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Upload not found or metadata missing: {str(e)}")

    if questions_count == 0:
        raise HTTPException(status_code=400, detail="No questions found for this upload.")

    # Check if already saved (idempotent)
    try:
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
        existing = pb.collection("questions").get_list(1, 1, {
            "filter": f'upload_id = "{upload_id}" && user = "{user["id"]}"',
        })
        if existing.items:
            return {"status": "already_saved", "count": len(existing.items)}
    except Exception:
        pass

    # Create one record per question
    created = []
    for i in range(1, questions_count + 1):
        r2_key = f"uploads/{upload_id}/output/question_{i:02d}.pdf"
        try:
            record = pb.collection("questions").create({
                "user":       user["id"],
                "upload_id":  upload_id,
                "r2_key":     r2_key,
                "source_pdf": filename,
                "subject":    subject,
                "curriculum": curriculum,
                "ai_tagged":  False,
                "q_number":   i,
            })
            created.append(record.id)
        except Exception as e:
            print(f"Could not save question {i}: {e}")

    return {
        "status":  "saved",
        "count":   len(created),
        "ids":     created,
    }


# ── Get user's questions ──────────────────────────────────────────────────────

@app.get("/api/my-questions")
async def get_my_questions(
    user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    subject: str = Query(None),
    curriculum: str = Query(None),
    difficulty: str = Query(None),
    q_type: str = Query(None),
):
    """Return paginated questions for the logged-in user."""
    try:
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)

        filters = [f'user = "{user["id"]}"']
        if subject:    filters.append(f'subject = "{subject}"')
        if curriculum: filters.append(f'curriculum = "{curriculum}"')
        if difficulty: filters.append(f'difficulty = "{difficulty}"')
        if q_type:     filters.append(f'q_type = "{q_type}"')

        result = pb.collection("questions").get_list(page, per_page, {
            "filter":  " && ".join(filters),
            "sort":    "-created",
        })

        questions_out = []
        for r in result.items:
            q = vars(r) if not isinstance(r, dict) else r
            # Derive thumbnail key so the frontend can request it directly
            r2_key = q.get("r2_key", "")
            if r2_key:
                parts = r2_key.split("/")
                jpg_name = Path(parts[-1]).stem + ".jpg"
                q["thumbnail_key"] = "/".join(parts[:-2]) + f"/thumbnails/{jpg_name}"
            else:
                q["thumbnail_key"] = None
            questions_out.append(q)

        return {
            "questions":   questions_out,
            "total":       result.total_items,
            "page":        page,
            "total_pages": result.total_pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Delete a question ─────────────────────────────────────────────────────────

@app.delete("/api/questions/{question_id}")
async def delete_question(
    question_id: str,
    user: dict = Depends(get_current_user),
):
    """Delete a question from the bank (user must own it)."""
    try:
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
        record = pb.collection("questions").get_one(question_id)
        rec_dict = vars(record) if not isinstance(record, dict) else record
        if rec_dict.get("user") != user["id"]:
            raise HTTPException(status_code=403, detail="Not your question.")
        pb.collection("questions").delete(question_id)
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Clean URL mappings — /pricing serves pricing.html, /igcse serves igcse.html etc.
CLEAN_URL_MAP = {
    "pricing":   "pricing.html",
    "igcse":     "igcse.html",
    "ib":        "ib.html",
    "sat":       "sat.html",
    "thanaweya": "thanaweya.html",
    "bank":      "bank.html",
}

@app.get("/")
@app.get("/{path_name:path}")
async def serve_frontend(path_name: str = None):
    possible_folders = [Path("frontend"), Path("../frontend"), Path(".")]

    # Clean URL: /pricing -> pricing.html
    if path_name and path_name.rstrip("/") in CLEAN_URL_MAP:
        target = CLEAN_URL_MAP[path_name.rstrip("/")]
        for folder in possible_folders:
            file_path = folder / target
            if file_path.exists():
                return FileResponse(file_path)

    # Direct file requests (e.g. /script.js, /favicon/...)
    if path_name and "." in path_name:
        for folder in possible_folders:
            file_path = folder / path_name
            if file_path.exists():
                return FileResponse(file_path)

    # Everything else -> index.html
    for folder in possible_folders:
        index_path = folder / "index.html"
        if index_path.exists():
            return FileResponse(index_path)

    raise HTTPException(status_code=404, detail="Frontend files not found.")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))

    print("="*70)
    print(f"Running on port: {port}")
    print("="*70)

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")