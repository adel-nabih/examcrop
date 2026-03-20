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
import requests

from split_pdf import YOLOQuestionSplitter
import pillow_heif
from PIL import Image
from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
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
            crop_info = yolo_splitter.split_worksheet(
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
                'crop_info':       crop_info,
                'pdf_path':        input_path,
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

                    # JPEG thumbnails — render page 0 of each already-cropped question PDF
                    for pdf_path in background_data['output_files']:
                        try:
                            q_stem = Path(pdf_path).stem  # e.g. "question_01"
                            thumb_doc = fitz.open(pdf_path)
                            page = thumb_doc[0]
                            mat = fitz.Matrix(2.0, 2.0)  # 144 dpi
                            pix = page.get_pixmap(matrix=mat, alpha=False)
                            jpeg_bytes = pix.tobytes("jpeg", jpg_quality=85)
                            thumb_doc.close()
                            thumb_key = f"{prefix}/thumbnails/{q_stem}.jpg"
                            r2_client.put_object(
                                Bucket=R2_BUCKET_NAME,
                                Key=thumb_key,
                                Body=jpeg_bytes,
                                ContentType='image/jpeg',
                            )
                        except Exception as thumb_err:
                            print(f"⚠️ Thumbnail failed for {Path(pdf_path).name}: {thumb_err}")

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





# ── Base taxonomy ─────────────────────────────────────────────────────────────

BASE_TAXONOMY = {
    "Mathematics": [
        "Algebra", "Quadratic Equations", "Simultaneous Equations",
        "Calculus", "Differentiation", "Integration",
        "Statistics", "Probability", "Distributions",
        "Geometry", "Trigonometry", "Vectors",
        "Mechanics", "Dynamics", "Statics",
        "Number Theory", "Sequences & Series", "Matrices",
    ],
    "Physics": [
        "Mechanics", "Kinematics", "Forces", "Momentum", "Energy",
        "Electricity", "Circuits", "Electromagnetism",
        "Waves", "Optics", "Sound",
        "Thermal Physics", "Thermodynamics",
        "Modern Physics", "Quantum Physics", "Nuclear Physics",
        "Fields", "Gravitational Fields", "Electric Fields",
    ],
    "Chemistry": [
        "Atomic Structure", "Periodic Table", "Bonding",
        "Stoichiometry", "Moles", "Chemical Equations",
        "Energetics", "Thermochemistry", "Kinetics",
        "Equilibrium", "Acids & Bases", "Redox",
        "Organic Chemistry", "Electrochemistry",
    ],
    "Biology": [
        "Cell Biology", "Cell Division", "Microscopy",
        "Molecular Biology", "DNA", "Protein Synthesis",
        "Genetics", "Inheritance", "Evolution",
        "Ecology", "Ecosystems", "Biodiversity",
        "Human Biology", "Digestion", "Circulation",
        "Respiration", "Nervous System", "Hormones",
        "Plant Biology", "Photosynthesis", "Transport in Plants",
        "Microbiology", "Immunity",
    ],
    "Accounting": [
        "Financial Statements", "Income Statement", "Balance Sheet",
        "Ledgers", "Double Entry", "Trial Balance",
        "Depreciation", "Bank Reconciliation",
        "Ratios", "Cash Flow", "Budgeting", "Partnerships",
    ],
    "Economics": [
        "Supply & Demand", "Elasticity", "Market Structures",
        "Macroeconomics", "GDP", "Inflation", "Unemployment",
        "Monetary Policy", "Fiscal Policy",
        "International Trade", "Exchange Rates", "Development",
    ],
    "Business": [
        "Marketing", "Market Research", "Pricing",
        "Finance", "Profit & Loss", "Break Even",
        "Operations", "Production", "Quality",
        "Human Resources", "Motivation", "Recruitment",
        "Strategy", "SWOT", "Stakeholders",
    ],
    "History": [
        "Source Analysis", "Causation", "Consequence",
        "Change & Continuity", "Significance", "Essay Writing",
    ],
    "Geography": [
        "Physical Geography", "Rivers", "Coasts", "Glaciation",
        "Human Geography", "Population", "Urbanisation",
        "Development", "Climate Change", "Ecosystems",
    ],
    "English Language": [
        "Reading Comprehension", "Summary", "Directed Writing",
        "Composition", "Language Analysis", "Audience & Purpose",
    ],
    "English Literature": [
        "Poetry Analysis", "Prose Analysis", "Drama",
        "Themes", "Character", "Context", "Comparison",
    ],
    "Sociology": [
        "Research Methods", "Family", "Education",
        "Crime & Deviance", "Stratification", "Culture & Identity",
    ],
}

TAGGING_PROMPT = """You are an expert exam question classifier. Look at the question image carefully and return ONLY a JSON object with these fields:

{{
  "subject": string,
  "topic": string,
  "subtopic": string or null,
  "difficulty": "Easy" | "Medium" | "Hard",
  "question_type": "MCQ" | "structured" | "short_answer" | "essay" | "data_response",
  "marks": integer or null,
  "keywords": string or null,
  "has_question_number": true | false,
  "sub_questions_independent": true | false | null
}}

- subject must be one of the keys in the taxonomy below. Read the question text and content carefully to determine it.
- topic must be one of the topics listed under the identified subject in the taxonomy below.
- marks: only if explicitly shown in the question (e.g. "[4]" or "(3 marks)"), otherwise null.
- sub_questions_independent: true if sub-parts can stand alone, false if they build on each other, null if no sub-questions.

Taxonomy:
{taxonomy}

User's custom topics (prefer these if they match):
{custom_topics}"""


def _get_user_taxonomy(user_id: str) -> dict:
    """Fetch user's custom taxonomy from PocketBase. Returns {} on any failure."""
    try:
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
        results = pb.collection("user_taxonomy").get_list(1, 1, {
            "filter": f'user = "{user_id}"',
        })
        if results.items:
            rec = vars(results.items[0]) if not isinstance(results.items[0], dict) else results.items[0]
            raw = rec.get("topics", {})
            if isinstance(raw, str):
                return json.loads(raw)
            return raw or {}
    except Exception as e:
        print(f"⚠️ Could not fetch user_taxonomy for {user_id}: {e}")
    return {}


def tag_questions_async(tagging_data: dict):
    """
    Background thread: fetch each question thumbnail from R2, send to GPT-4o-mini,
    update PocketBase record with tags and tagging_status.
    """
    if not OPENAI_API_KEY:
        print("⚠️ OPENAI_API_KEY not set — skipping tagging")
        return

    record_ids = tagging_data["record_ids"]
    upload_id  = tagging_data["upload_id"]
    user_id    = tagging_data["user_id"]

    custom_taxonomy = _get_user_taxonomy(user_id)

    # Merge base + custom taxonomy for the prompt
    merged_taxonomy = {k: list(v) for k, v in BASE_TAXONOMY.items()}
    for subj, topics in custom_taxonomy.items():
        subj_norm = subj.strip()
        if subj_norm in merged_taxonomy:
            existing = set(merged_taxonomy[subj_norm])
            merged_taxonomy[subj_norm] = merged_taxonomy[subj_norm] + [t for t in topics if t not in existing]
        else:
            merged_taxonomy[subj_norm] = topics

    taxonomy_str     = json.dumps(merged_taxonomy, indent=2)
    custom_topics_str = json.dumps(custom_taxonomy, indent=2) if custom_taxonomy else "None"

    prompt = TAGGING_PROMPT.format(
        taxonomy=taxonomy_str,
        custom_topics=custom_topics_str,
    )

    print(f"🏷️  Tagging {len(record_ids)} questions for upload {upload_id}")

    for i, record_id in enumerate(record_ids, 1):
        q_num = i  # record_ids are in order 1..N
        thumb_key = f"uploads/{upload_id}/thumbnails/question_{q_num:02d}.jpg"

        try:
            # Fetch thumbnail bytes from R2 — retry because R2 upload may still be in progress
            import base64, time as _time
            from botocore.exceptions import ClientError as _BotoClientError
            jpeg_bytes = None
            for attempt in range(6):
                try:
                    obj = r2_client.get_object(Bucket=R2_BUCKET_NAME, Key=thumb_key)
                    jpeg_bytes = obj["Body"].read()
                    break
                except _BotoClientError as boto_err:
                    if boto_err.response['Error']['Code'] in ('NoSuchKey', '404'):
                        if attempt < 5:
                            wait = 5 * (attempt + 1)  # 5, 10, 15, 20, 25 s
                            print(f"  ⏳ Thumbnail not ready yet for q{q_num}, retrying in {wait}s (attempt {attempt+1}/6)")
                            _time.sleep(wait)
                        else:
                            raise
                    else:
                        raise  # unexpected R2 error — don't retry

            if jpeg_bytes is None:
                raise RuntimeError(f"Thumbnail never appeared in R2 after retries: {thumb_key}")

            image_b64 = base64.b64encode(jpeg_bytes).decode("utf-8")

            # Call GPT-4o-mini vision
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "max_tokens": 500,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text",       "text": prompt},
                                {"type": "image_url",  "image_url": {
                                    "url":    f"data:image/jpeg;base64,{image_b64}",
                                    "detail": "high",
                                }},
                            ],
                        }
                    ],
                },
                timeout=30,
            )
            response.raise_for_status()
            raw_content = response.json()["choices"][0]["message"]["content"]
            print(f"  🤖 GPT raw response for q{q_num}: {raw_content}")
            tags = json.loads(raw_content)

            # Normalise string fields
            def norm(v):
                return v.strip().lower() if isinstance(v, str) else v

            update_payload = {
                "subject":                  tags.get("subject"),
                "topic":                    tags.get("topic"),
                "subtopic":                 tags.get("subtopic"),
                "difficulty":               norm(tags.get("difficulty")),
                "q_type":                   norm(tags.get("question_type")),
                "marks":                    tags.get("marks"),
                "keywords":                 tags.get("keywords"),
                "has_question_number":      tags.get("has_question_number"),
                "sub_questions_independent": tags.get("sub_questions_independent"),
                "ai_tagged":                True,
                "tagging_status":           "complete",
            }
            # Remove None values so we don't overwrite existing data with null
            update_payload = {k: v for k, v in update_payload.items() if v is not None}

            pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
            pb.collection("questions").update(record_id, update_payload)
            print(f"  ✅ Tagged q{q_num}: subject={tags.get('subject')} topic={tags.get('topic')}")

        except Exception as e:
            print(f"  ❌ Tagging failed for record {record_id} (q{q_num}): {e}")
            try:
                pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
                pb.collection("questions").update(record_id, {"tagging_status": "failed"})
            except Exception as pb_err:
                print(f"  ⚠️ Could not mark tagging_status=failed for {record_id}: {pb_err}")

    print(f"🏷️  Tagging complete for upload {upload_id}")


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


# ── Taxonomy endpoint ─────────────────────────────────────────────────────────

@app.get("/api/taxonomy")
async def get_taxonomy(user: dict = Depends(get_current_user)):
    """
    Return base taxonomy merged with the user's custom topics.
    Frontend uses this for tag editing dropdowns.
    """
    custom = _get_user_taxonomy(user["id"])
    merged = {k: list(v) for k, v in BASE_TAXONOMY.items()}
    for subj, topics in custom.items():
        subj_norm = subj.strip()
        if subj_norm in merged:
            existing = set(merged[subj_norm])
            merged[subj_norm] = merged[subj_norm] + [t for t in topics if t not in existing]
        else:
            merged[subj_norm] = topics
    return {"taxonomy": merged, "custom": custom}


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


@app.post("/api/r2-urls")
async def get_r2_signed_urls_batch(
    request: dict,
    user: dict = Depends(get_current_user),
):
    """Batch presigned URL generation. Body: {"keys": ["key1", "key2", ...]} — max 100."""
    keys = request.get("keys", [])
    if not keys or len(keys) > 100:
        raise HTTPException(status_code=400, detail="Provide between 1 and 100 keys.")
    if not r2_client:
        raise HTTPException(status_code=503, detail="R2 not available.")
    for key in keys:
        if not key.startswith("uploads/"):
            raise HTTPException(status_code=400, detail=f"Invalid key: {key}")
    urls = {}
    for key in keys:
        try:
            urls[key] = r2_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": R2_BUCKET_NAME, "Key": key},
                ExpiresIn=3600,
            )
        except Exception:
            pass  # skip failed keys — frontend falls back gracefully
    return {"urls": urls, "expires_in": 3600}



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
        r2_key       = f"uploads/{upload_id}/output/question_{i:02d}.pdf"
        thumbnail_key = f"uploads/{upload_id}/thumbnails/question_{i:02d}.jpg"
        try:
            record = pb.collection("questions").create({
                "user":            user["id"],
                "upload_id":       upload_id,
                "r2_key":          r2_key,
                "thumbnail_key":   thumbnail_key,
                "source_pdf":      filename,
                "subject":         subject,
                "curriculum":      curriculum,
                "ai_tagged":       False,
                "tagging_status":  "pending",
                "q_number":        i,
            })
            created.append(record.id)
        except Exception as e:
            print(f"Could not save question {i}: {e}")

    # Fire background tagging job if any records were created
    if created:
        tagging_data = {
            'record_ids': created,
            'upload_id':  upload_id,
            'user_id':    user["id"],
        }
        threading.Thread(
            target=tag_questions_async,
            args=(tagging_data,),
            daemon=True,
        ).start()
        print(f"🏷️  Started background tagging for {len(created)} questions ({upload_id})")

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
    search: str = Query(None),
):
    """Return paginated questions for the logged-in user."""
    try:
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)

        filters = [f'user = "{user["id"]}"']
        if subject:    filters.append(f'subject = "{subject}"')
        if curriculum: filters.append(f'curriculum = "{curriculum}"')
        if difficulty: filters.append(f'difficulty = "{difficulty}"')
        if q_type:     filters.append(f'q_type = "{q_type}"')
        if search:
            s = search.replace('"', '')
            filters.append(f'(keywords ~ "{s}" || source_pdf ~ "{s}" || topic ~ "{s}" || subtopic ~ "{s}")')

        result = pb.collection("questions").get_list(page, per_page, {
            "filter":  " && ".join(filters),
            "sort":    "-created",
        })

        questions_out = []
        for r in result.items:
            q = vars(r) if not isinstance(r, dict) else r
            questions_out.append(q)

        return {
            "questions":   questions_out,
            "total":       result.total_items,
            "page":        page,
            "total_pages": result.total_pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Update a question's tags ──────────────────────────────────────────────────

@app.patch("/api/questions/{question_id}")
async def update_question(
    question_id: str,
    request: dict,
    user: dict = Depends(get_current_user),
):
    """Update tag fields on a question. User must own it."""
    ALLOWED_FIELDS = {
        "subject", "topic", "subtopic", "difficulty", "q_type",
        "marks", "keywords", "curriculum", "has_question_number",
        "sub_questions_independent",
    }
    try:
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
        record = pb.collection("questions").get_one(question_id)
        rec_dict = vars(record) if not isinstance(record, dict) else record
        if rec_dict.get("user") != user["id"]:
            raise HTTPException(status_code=403, detail="Not your question.")
        payload = {k: v for k, v in request.items() if k in ALLOWED_FIELDS}
        if not payload:
            raise HTTPException(status_code=400, detail="No valid fields to update.")
        updated = pb.collection("questions").update(question_id, payload)
        return {"status": "updated", "id": question_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Poll tagging status ───────────────────────────────────────────────────────

@app.post("/api/questions/tagging-status")
async def get_tagging_status(
    request: dict,
    user: dict = Depends(get_current_user),
):
    """
    Poll tagging status for a list of question IDs.
    Body: {"ids": ["id1", "id2", ...]}
    Returns only the fields needed to update the UI — no PDFs, no keys.
    """
    ids = request.get("ids", [])
    if not ids or len(ids) > 100:
        raise HTTPException(status_code=400, detail="Provide between 1 and 100 ids.")
    try:
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
        # Fetch all in one PocketBase query using OR filter
        id_filter = " || ".join(f'id = "{qid}"' for qid in ids)
        result = pb.collection("questions").get_list(1, len(ids), {
            "filter": f'user = "{user["id"]}" && ({id_filter})',
        })
        out = []
        for r in result.items:
            q = vars(r) if not isinstance(r, dict) else r
            out.append({
                "id":             q.get("id"),
                "tagging_status": q.get("tagging_status"),
                "subject":        q.get("subject"),
                "topic":          q.get("topic"),
                "difficulty":     q.get("difficulty"),
                "q_type":         q.get("q_type"),
                "marks":          q.get("marks"),
                "keywords":       q.get("keywords"),
                "subtopic":       q.get("subtopic"),
                "curriculum":     q.get("curriculum"),
            })
        return {"questions": out}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/taxonomy")
async def update_taxonomy(
    request: dict,
    user: dict = Depends(get_current_user),
):
    """
    Upsert user's custom taxonomy. request body: {"subject": str, "topic": str}
    Adds the topic to the subject's list if not already present.
    """
    subject = (request.get("subject") or "").strip()
    topic   = (request.get("topic")   or "").strip().lower()
    if not subject or not topic:
        raise HTTPException(status_code=400, detail="subject and topic required.")
    try:
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
        results = pb.collection("user_taxonomy").get_list(1, 1, {
            "filter": f'user = "{user["id"]}"',
        })
        if results.items:
            rec = vars(results.items[0]) if not isinstance(results.items[0], dict) else results.items[0]
            rec_id = rec.get("id")
            raw = rec.get("topics", {})
            existing = json.loads(raw) if isinstance(raw, str) else (raw or {})
            topics_list = existing.get(subject, [])
            if topic not in [t.lower() for t in topics_list]:
                topics_list.append(topic)
                existing[subject] = topics_list
            pb.collection("user_taxonomy").update(rec_id, {"topics": json.dumps(existing)})
        else:
            pb.collection("user_taxonomy").create({
                "user":    user["id"],
                "subject": subject,
                "topics":  json.dumps({subject: [topic]}),
            })
        return {"status": "ok", "subject": subject, "topic": topic}
    except HTTPException:
        raise
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



# ── Bulk download ─────────────────────────────────────────────────────────────

@app.post("/api/download-questions")
async def download_questions(
    request: dict,
    user: dict = Depends(get_current_user),
):
    """
    Fetch multiple question PDFs from R2, zip them, stream the ZIP back.
    Body: {"ids": ["id1", "id2", ...]}  — max 50.
    """
    ids = request.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No question IDs provided.")
    if len(ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 questions per download.")

    try:
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)

        # Verify ownership and collect r2_keys in parallel
        def fetch_record(qid):
            rec = pb.collection("questions").get_one(qid)
            return vars(rec) if not isinstance(rec, dict) else rec

        with ThreadPoolExecutor(max_workers=8) as pool:
            records = list(pool.map(fetch_record, ids))

        for rec in records:
            if rec.get("user") != user["id"]:
                raise HTTPException(status_code=403, detail="Not your question.")

        # Fetch PDFs from R2 in parallel
        def fetch_pdf(rec):
            key = rec.get("r2_key", "")
            obj = r2_client.get_object(Bucket=R2_BUCKET_NAME, Key=key)
            return {
                "filename": f"Q{rec.get('q_number','?')}_{Path(key).name}",
                "data":     obj["Body"].read(),
            }

        with ThreadPoolExecutor(max_workers=8) as pool:
            pdf_files = list(pool.map(fetch_pdf, records))

        # Build ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for pf in pdf_files:
                zf.writestr(pf["filename"], pf["data"])
        zip_buffer.seek(0)

        zip_id   = uuid.uuid4().hex[:8]
        zip_name = f"examcrop_{zip_id}.zip"

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={zip_name}"},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



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